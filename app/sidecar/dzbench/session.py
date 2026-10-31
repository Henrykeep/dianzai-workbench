"""一次连接的全部状态：收帧 → 解码 → 缓存；参数读写（等 ACK、重发）；急停；原始日志。

线程模型：传输层后台线程调用 _on_bytes；对外 API 线程安全；事件通过 emit 回调送出（server 负责转到 asyncio）。
"""
from __future__ import annotations

import itertools
import collections
import pathlib
import re
import datetime
import struct
import threading
import time
from typing import Callable

from . import latch, lastsession, snapshots
from ._dzlink import DATA, HEARTBEAT, PARAM_ACK, PARAM_SET, Parser, encode
from .textparse import KvParser
from .framedef import FrameDefError, FrameDefParser
from .events import Timeline, crc_spike
from .linkhealth import LinkHealth
from .linkstate import LinkState
from .logfile import RX, TX, LogWriter
from . import ports as _ports
from .ports import PortOpenError, explain_open_error, identity, probe_baud
from .schema import check_value
from .stepproto import dzstep, STEP_ID as ID_STEP, REJECT_ID as ID_REJECT, HB_ITER_BUSY
from .replay import ReplayTransport
from .schema import Schema, find_by_hash
from .transport import SIM_PREFIX, Transport, open_transport

ID_CMD, ID_ESTOP = 0x7E, 0x7F
ACK_STATUS = {0: "ok", 1: "clamped", 2: "bad_id", 3: "bad_len", 4: "bad_value", 5: "rejected"}   # 5 = dzctl 0.13.0 被拒（回读值 = 旧值）
HB_TIMEOUT_S = 2.0          # = linkstate.LOST_AFTER_S；板子心跳 500 ms，任一合法帧都算活着


class LinkError(Exception):
    """带“怎么修”的错误：UI 原样显示 message 和 fix。"""

    def __init__(self, code: str, message: str, fix: str = "", fix_action: str | None = None, extra: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.fix, self.fix_action, self.extra = code, message, fix, fix_action, extra or {}

    def as_dict(self) -> dict:
        d = {"type": "error", "code": self.code, "message": self.message, "fix": self.fix} | self.extra
        if self.fix_action:
            d["fix_action"] = self.fix_action
        return d


REJECT_ZH = {"range": "超出允许范围", "type": "类型不对（整数参数给了小数等）", "state": "板子当前状态不允许改（迭代/实验进行中或急停）",
             "step": "单步改动过大（超过 max_delta）", "busy": "自动迭代进行中，参数已锁定，结束或停止迭代后再改", "unknown": "板子拒绝了这次写入"}


class Session:
    def __init__(self, emit: Callable[[dict], None] = lambda e: None, log_dir: pathlib.Path | None = None,
                 history_s: float = 120.0):
        self.emit = emit
        self._conn_lock = threading.Lock()       # r9q (d)：连接串行化，界面/脚本重复点“连接”不再打断正在启动的仿真板
        self.log_dir = log_dir or snapshots.base_dir() / "logs"
        self.lock = threading.RLock()
        self.wlock = threading.Lock()
        self._estop_seq = itertools.count(1)
        # 收线程不等 session.lock：心跳/急停位/estop_cause 只用 hblock（小锁）；要 session.lock 的活（日志、遥测入库、参数回执…）
        # 拿不到锁就按序排进 _deferred，由 dz-rxapply 线程拿到锁后依次补做（顺序不乱）
        self.rxlock = threading.Lock()
        self.hblock = threading.RLock()
        self.linklock = threading.Lock()
        self._deferred: collections.deque = collections.deque()
        self._defer_ev = threading.Event()
        self._applier: threading.Thread | None = None
        self._binding_h: int | None = None        # 只护“写串口”这一小段：帧不交错；急停不等 self.lock
        self.history_s = history_s
        self._open = open_transport          # 测试可注入
        self.host_hb = True                  # 测试用开关：False 模拟侧车卡死
        self._gen = 0                        # 每次 connect/disconnect +1，用来取消旧的自动重连
        self.auto_reconnect = True
        self.stall_s = 0.0                   # >0：串口开着但这么久一个字节都没收到（之前收到过）= 当断线处理并重连
        self.on_sample: Callable[[dict], None] | None = None   # 触发发送用
        self.raw_on = False                  # 原始监视器（文本/HEX）开着才收集，省内存
        self.link = LinkState()              # 跨连接保留：since / seq 连续
        self.down_reason = ""                # board=disconnected 时的原因（如 port_not_found）；connect/disconnect 清掉
        self.resuming = False                # 侧车重启后正在自动连回上次的板子
        self._uid_marked = False
        self._reset()

    def _reset(self) -> None:
        self.tr: Transport | None = None
        self.port = ""
        self.baud = 0
        self.parser = Parser()
        self.health = LinkHealth()
        self.timeline = Timeline()
        self._was_alive = False
        self._pending_marks: list[tuple[str, str]] = []
        self.bb_recs: list[dict] = []             # 最近一次黑匣子导出（DATA 0x7D）
        self.schema: Schema | None = None
        self.schema_hash: int | None = None
        self.board_uid: int | None = None        # 心跳里的芯片 ID（dzctl 0.3.0+；0/没有 = 未知）
        self.selftest: dict | None = None        # dzctl 0.10.0 心跳尾部自检结果（selftest_dict），旧固件 / 应用没报 = None
        self.params_hash: int | None = None
        self._estop_hold = False
        self._estop_held: list[dict] = []
        self._cause_announced = False
        self._hb_clear_t_ms: int | None = None
        self._selftest_key: tuple | None = None   # 心跳里 (mask, t_ms)：变了才算新的一次自检
        self.selftest_at: str | None = None       # 自检完成时间（ISO，本机时区）
        self.selftest_ph: int | None = None       # 自检时的参数 hash；与当前 params_hash 不同 → stale
        self.estop_cause: dict | None = None     # dzctl 0.8.0 心跳里的急停原因（estop_cause_dict），没急停 = None
        self.hb_status: int | None = None        # dzctl 0.5.0 心跳第 4 个 u32：低 8 位复位原因 + DZCTL_HB_* 标志
        self.h_supported = False                 # 本次连接里板子回过 'H'（dzctl 0.12.0+）
        self.fw_rev: int | None = None           # 心跳里的固件版本（dzctl 0.4.0+：git 短哈希，bit31 = 有未提交改动）
        self.samples: collections.deque = collections.deque()
        self._new: list = []
        self.params: dict[str, float] = {}
        self._acks: dict[int, tuple[threading.Event, list]] = {}
        self.rx_bytes = 0
        self.last_hb = 0.0
        self.last_rx = 0.0
        self.last_frame = 0.0                    # 最近一帧合法帧（任意类型），link.state 据此判活
        self.log: LogWriter | None = None
        self.seq = 0
        self.estop_count = 0
        self.t_connect = 0.0
        self.reconnecting = False
        self.reconnects = 0
        self.reconnect_attempt = 0
        self._t_tr = 0.0
        self._rx_seen = False               # 当前传输开了以后收到过字节没有（卡死检测用；不用时间戳比较——Windows 时钟粒度 15.6 ms，last_rx 会等于 _t_tr）
        self._raw: collections.deque = collections.deque()
        self._raw_bytes = 0
        self.raw_dropped = 0
        self.kv = KvParser()
        self._uid_marked = False
        self.param_writes = 0                # 本次连接写参数的次数（进度：判断参数是否已写入 Flash）
        self.flash_saved_writes = -1         # 黑匣子报“参数已存进 flash / 上电读了 flash”时的 param_writes；-1 = 没见过
        self.run_mode: str | None = None     # 板子运行模式 tethered / standalone；固件上报后才有，否则 None
        self.tx_locked = False               # 急停后锁住侧车的一切主动发送；只有人点“解除急停”才解（重连/侧车重启都不解，见 latch.py）
        self.step_cv = threading.Condition()   # #38 阶跃应答 / step_result / param_reject（收线程写，调用方等）
        self.step_ack: dict | None = None
        self.step_results: list[dict] = []
        self.last_reject: dict | None = None
        self._sp_live: dict[str, float] = {}   # 未锁存时遥测里的设定值（ref_for 字段）；锁存后不再更新
        self.sp_before_latch: float | None = None   # 急停前主设定值（界面「恢复急停前目标」）；setpoint_set 成功后清掉
        self._sp_frozen = False
        self.clear_pending_at: float | None = None   # 发了 'R'、等固件心跳 bit10 清零确认的起点（monotonic）
        self.estop_requested_at: float | None = None
        self.estop_source: str | None = None  # 当前锁存的来源：ui / agent / heartbeat_lost / firmware:<cause> / selftest / latch_restored

    # ------------------------------------------------------------------ 连接
    def connect(self, port: str, baud: int | None = None, log: bool = True) -> dict:
        """r9q (d) 根因：首次连仿真板要先 make 编出 host-sim 程序（干净工作区约 10–15 s），期间以前什么都不推、连接回复也不来，
        界面一直是“未连接”，用户/脚本就再点一次“连接”——第二次先 disconnect 再从头编，于是 18 s + 重连。
        现在：编译前后推 sim_starting（start / ready，带耗时）；连接串行化，排队的同口连接在前一个连上后直接复用，不再拆掉重来。"""
        with self._conn_lock:
            if port.startswith(SIM_PREFIX) and port == self.port and self.tr is not None:
                return {"port": port, "baud": self.baud, "note": "已连上（复用刚启动的仿真板）", "reused": True}
            prev = getattr(self, "_last_port", None)
            r = self._connect(port, baud, log)
            self._last_port = port
            for h in list(getattr(self, "connect_hooks", [])):   # #101：重连 / 换板 → 服务层清结果卡
                try:
                    h(port, prev)
                except Exception:  # noqa: BLE001  钩子出错不影响连接本身
                    pass
            return r

    def _connect(self, port: str, baud: int | None = None, log: bool = True) -> dict:
        self.disconnect()
        note = ""
        if not port.startswith((SIM_PREFIX, "replay:", "rtt:")) and not baud:
            try:
                baud, note = probe_baud(port)
            except PortOpenError as e:
                raise LinkError("open_failed", e.what, e.fix) from e
            if not baud:
                raise LinkError("no_frames", note, "也可以在波特率下拉框手动选一个再连；不是工作台固件的设备"
                                "（视觉模块 printf、蓝牙 AT…）手动选波特率连上后，切到“原始”视图看收发")
        try:
            t_open = time.monotonic()
            if port.startswith(SIM_PREFIX):
                self.emit({"type": "sim_starting", "port": port, "state": "start", "message_zh": "正在启动仿真板（首次要编译，约 10–20 s）"})
            tr = ReplayTransport(port[7:]) if port.startswith("replay:") else self._open(port, baud or 0)
            if port.startswith(SIM_PREFIX):
                self.emit({"type": "sim_starting", "port": port, "state": "ready", "elapsed_s": round(time.monotonic() - t_open, 2)})
        except Exception as e:  # noqa: BLE001
            if port.startswith(SIM_PREFIX):
                raise LinkError("open_failed", f"仿真板起不来：{e}", f"在仓库根目录跑一次 make BOARD=host-sim APP={port[len(SIM_PREFIX):].split('+')[0]} 看报错") from e
            what, fix = explain_open_error(port, e)
            raise LinkError("open_failed", what, fix) from e
        self.ident = identity(port) if not port.startswith((SIM_PREFIX, "replay:")) else None
        lastsession.mark(port, baud or 0, self.ident)
        self.down_reason = ""
        self.health.reset()
        with self.lock:
            self.tr, self.port, self.baud, self.t_connect = tr, port, baud or 0, time.monotonic()
            self._t_tr = self.t_connect
            self._rx_seen = False
            self.hb_status = None
            self.estop_cause = None
            self._cause_announced = False          # 本次连接是否已推过带 cause 的 latched（连上时板子已急停、没有 bit10 上升沿也要推一次）
            self._hb_clear_t_ms = None
            self.selftest = None; self.params_hash = None; self._selftest_key = self.selftest_at = self.selftest_ph = None
            rec = None if isinstance(tr, ReplayTransport) else latch.get(port, None)
            if rec:                                # 缺口 #20：重连只恢复通信/遥测，急停锁存保持
                self.tx_locked = True
                self.estop_source = rec.get("source") or "latch_restored"
                self.estop_cause = rec.get("cause")    # 原因随锁存一起保留，直到人解除急停（重连后不再变 null）
            if isinstance(tr, ReplayTransport) and tr.header.get("schema_hash"):
                self._bind_schema(int(tr.header["schema_hash"], 16))
            if log and not isinstance(tr, ReplayTransport):
                self.start_log()
        with self.lock:
            self._gen += 1
            gen = self._gen
        tr.start(self._on_bytes, lambda msg: self._on_transport_error(msg, gen))
        if self.tx_locked:
            self.emit({"type": "tx_locked", "on": True, "source": self.estop_source, "restored": True})
            self.mark("estop", "重连后保持急停锁存（上次急停尚未由人解除）", source=self.estop_source or "latch_restored")
        if not isinstance(tr, ReplayTransport):
            threading.Thread(target=self._host_heartbeat, args=(gen,), daemon=True).start()
        return {"port": port, "baud": baud, "note": note}

    HOST_HB_PERIOD_S = 0.25   # 固件 dzctl_wd 超时 1000 ms：侧车崩溃/拔线 -> 板子输出归零并锁存急停

    def _host_heartbeat(self, gen: int) -> None:
        """认出工作台固件（收到带 schema 的心跳）后，每 250 ms 发一帧上位机心跳（HEARTBEAT, LEN=0）。
        非工作台设备（AT 模块、printf）从不绑定 schema，就不会收到这些字节。急停锁定期间照发（心跳不驱动执行器）。
        心跳根因修复：以前每拍先拿 session.lock（日志、遥测入库、参数回执、阶跃等长活都持有它），再经 _send 又拿一次，
        长持锁时这一拍被拖到 750 ms 以上 → 板端 1000 ms 看门狗差 1 ms 就锁存急停。现在：专用线程、按单调时钟定拍（不累积漂移），
        不碰 session.lock，只用写锁 wlock 发 0 字节心跳帧；_stall_check 放在发送之后。"""
        nxt = time.monotonic()
        while True:
            nxt += self.HOST_HB_PERIOD_S
            dt = nxt - time.monotonic()
            if dt > 0:
                time.sleep(dt)
            else:
                nxt = time.monotonic()                       # 落后了就从现在重新定拍，不连发补拍
            if gen != self._gen and not self.reconnecting:
                return
            tr = self.tr
            if self.schema_hash is not None and tr is not None and self.host_hb:
                self._send_hb(tr)
            self._stall_check(gen)

    def _send_hb(self, tr) -> None:
        """上位机心跳专用发送：只拿写锁，不拿 session.lock；记下实际发送间隔（hb_gap_max_ms）。"""
        now = time.monotonic()
        last = getattr(self, "hb_sent_at", None)
        if last is not None:
            self.hb_gap_max_ms = max(getattr(self, "hb_gap_max_ms", 0.0), (now - last) * 1000)
        self.hb_sent_at = now
        try:
            with self.wlock:
                self.seq = (self.seq + 1) & 0xFF
                frame = encode(HEARTBEAT, 0, self.seq, b"")
                tr.write(frame)
        except Exception:  # noqa: BLE001  传输层错误交给读线程的重连逻辑
            pass

    def _stall_check(self, gen: int) -> None:
        """USB 转串口卡死（CH340 / CP210x 偶发：口还在、驱动不报错、就是不来数据）：开了 stall_s 才查。"""
        if not self.lock.acquire(blocking=False):        # 心跳线程里调：别人持锁就下一拍再查，绝不让心跳等锁
            return
        try:
            if not (self.stall_s > 0 and self.tr is not None and not self.reconnecting and gen == self._gen
                    and getattr(self.tr, "ser", None) is not None and self._rx_seen):
                return
            idle = time.monotonic() - self.last_rx
        finally:
            self.lock.release()
        if idle > self.stall_s:
            self._on_transport_error(f"{idle:.1f} s 没收到任何字节（串口卡死？）", gen)

    # ------------------------------------------------------------------ DTR / RTS（缺口 14）
    # 脉冲序列：(DTR, RTS, 保持 ms)。pyserial 的 True = 线有效 = 引脚低电平（经 USB 转串口芯片反相）。
    # esp_boot / esp_reset 参考 esptool 的 ClassicReset / HardReset；stm32_* 是 FlyMCU 常见接法（DTR→NRST、RTS→BOOT0，经三极管），
    # 板子接法不同就会反，所以只在人点按钮时执行，执行后线状态回到“不拉”。
    PULSES = {
        "esp_reset": [(False, True, 100), (False, False, 0)],
        "esp_boot": [(False, True, 100), (True, False, 50), (False, False, 0)],
        "stm32_reset": [(True, False, 100), (False, False, 0)],
        "stm32_boot": [(True, True, 100), (False, True, 200), (False, False, 0)],
    }

    def _ser(self):
        with self.lock:
            tr = self.tr
        ser = getattr(tr, "ser", None)
        if ser is None:
            raise LinkError("not_serial", "只有真串口能控制 DTR/RTS（仿真板 / 回放 / RTT 没有这两根线）", "先连上 USB 转串口")
        return ser

    def serial_modem(self) -> dict:
        ser = self._ser()
        out = {"dtr": bool(ser.dtr), "rts": bool(ser.rts)}
        for k in ("cts", "dsr", "ri", "cd"):
            try:
                out[k] = bool(getattr(ser, k))
            except Exception:  # noqa: BLE001  有的驱动不支持读调制解调器线
                out[k] = None
        return out

    def serial_lines_set(self, dtr: bool | None = None, rts: bool | None = None) -> dict:
        """连着的时候直接改线电平；同时记进 ports.LINES，自动重连 / 下次打开沿用。"""
        ser = self._ser()
        for k, v in (("dtr", dtr), ("rts", rts)):
            if v is not None:
                setattr(ser, k, bool(v))
                _ports.LINES[k] = bool(v)
        _ports.LINES.setdefault("dtr", None); _ports.LINES.setdefault("rts", None)
        return self.serial_modem()

    def serial_pulse(self, name: str) -> dict:
        seq = self.PULSES.get(name)
        if seq is None:
            raise LinkError("bad_pulse", f"没有脉冲序列 {name}（有 {' / '.join(self.PULSES)}）")
        ser = self._ser()
        for dtr, rts, ms in seq:
            ser.dtr, ser.rts = dtr, rts
            if ms:
                time.sleep(ms / 1000)
        _ports.LINES.update({"dtr": False, "rts": False})
        return {"pulse": name, "steps": len(seq), **self.serial_modem()}

    def disconnect(self) -> None:
        lastsession.clear()                   # 用户主动断开 = 正常结束（侧车崩了不会走到这里）；也取消重启后的自动重连
        self.down_reason = ""
        with self.lock:
            self._gen += 1                    # 主动断开：取消自动重连
            tr, log = self.tr, self.log
            self.tr = None
        if tr:
            tr.close()
        if log:
            log.close()
        with self.lock:
            self._reset()

    def _on_transport_error(self, msg: str, gen: int | None = None) -> None:
        with self.lock:
            stale = gen is not None and gen != self._gen
            port, baud = self.port, self.baud
            can = (self.auto_reconnect and not stale and self.tr is not None
                   and not port.startswith((SIM_PREFIX, "replay:")))
            if can:
                old, self.tr, self.reconnecting = self.tr, None, True
            # #57：仿真进程没了（被杀 / 崩溃）→ 传输层摘掉，唯一状态源 link.state 走 disconnected（reason=sim_exited），
            # status.connected 跟着变 false；不自动重起仿真（那等于偷偷换了一块新板），用户点“连接”再起
            dead = (not can and not stale and self.tr is not None and port.startswith(SIM_PREFIX))
            if dead:
                old, self.tr, self.down_reason = self.tr, None, "sim_exited"
        if stale:
            return
        if dead:
            try:
                old.close()
            except Exception:  # noqa: BLE001
                pass
            self.emit(LinkError("link_lost", f"仿真板已退出：{msg}", "点“连接”重新启动仿真板").as_dict())
            return
        if not can:
            self.emit(LinkError("link_lost", f"连接断开：{msg}", "检查 USB 线/供电；板子复位后点“连接”重连").as_dict())
            return
        try:
            old.close()
        except Exception:  # noqa: BLE001
            pass
        self.emit(LinkError("link_lost", f"连接断开：{msg}", "正在自动重连（线插回去即可）；不想重连就点“断开”").as_dict())
        threading.Thread(target=self._reconnect_loop, args=(port, baud, gen), daemon=True).start()

    RECONNECT_BACKOFF = (0.25, 0.5, 1.0, 2.0, 4.0)

    def _reconnect_loop(self, port: str, baud: int, gen: int | None) -> None:
        """指数退避重开同一个口（同一波特率），直到成功或用户主动断开；成功后重读全部参数。
        板子在断线期间应已按心跳超时自行进入安全状态（docs/dev/QUESTIONS.md 决定 1），这里不自动解除急停。"""
        k, warned = 0, False
        while True:
            delay = self.RECONNECT_BACKOFF[min(k, len(self.RECONNECT_BACKOFF) - 1)]
            time.sleep(delay)
            k += 1
            self.reconnect_attempt = k
            if k == 1 or k % 5 == 0:
                self.emit({"type": "reconnecting", "port": port, "attempt": k, "next_s": self.RECONNECT_BACKOFF[min(k, len(self.RECONNECT_BACKOFF) - 1)]})
            with self.lock:
                if gen != self._gen:
                    return
            try:
                tr = self._open(port, baud)
            except Exception:  # noqa: BLE001
                moved, why = _ports.pick_moved(port, getattr(self, "ident", None), self.board_uid,
                                               self.schema_hash, baud)               # 同一块板插到别的口 / 换了 COM 号
                if why == "ambiguous" and not warned:
                    warned = True
                    self.emit(LinkError("port_ambiguous", f"{port} 不见了，但现在插着好几块同型号的板，分不清哪块是刚才那块，没有自动跟过去",
                                        "在端口列表里手动选一下再点“连接”；固件升到 dzctl 0.3.0（心跳带板 ID）后就能自动认板").as_dict())
                if not moved:
                    continue
                try:
                    tr = self._open(moved, baud)
                except Exception:  # noqa: BLE001
                    continue
                self.emit({"type": "port_moved", "old": port, "new": moved,
                           "message": f"板子的串口从 {port} 变成了 {moved}（换了 USB 口？），已经跟过去"})
                with self.lock:
                    self.port = port = moved
            with self.lock:
                if gen != self._gen:
                    tr.close()
                    return
                self.tr, self.reconnecting = tr, False
                self.reconnects += 1
                self.reconnect_attempt = 0
                self._t_tr = time.monotonic()
                self._rx_seen = False
                self.parser = Parser()
                self.health.rebase()
                t_open = time.monotonic()
            tr.start(self._on_bytes, lambda msg: self._on_transport_error(msg, gen))
            self.emit({"type": "reconnected", "port": port, "attempts": k, "message": f"已自动重连 {port}（第 {k} 次尝试），正在重读参数"})
            for _ in range(40):                       # 等心跳再读参数（最多 2 s）
                if self.last_hb > t_open:
                    break
                time.sleep(0.05)
            if self.schema:
                try:
                    self.read_all_params()
                except Exception:  # noqa: BLE001
                    pass
            return

    RESUME_TRIES = (0.0, 0.3, 0.6, 1.0)      # 侧车重启后重开原口的间隔（总共约 2 s，留余量给 3 s 内连上）

    def resume(self, rec: dict) -> dict:
        """侧车重启后自动连回上次的板子：先试原口；打不开就按记下的 USB 身份/板 ID 重扫端口；
        都不行 → board=disconnected、reason=port_not_found，记录放回去（下次重启再试，用户点“断开”才放弃）。
        只恢复链路，不解除急停。用户在这期间点了连接/断开（_gen 变了）就让位。
        硬规则（统筹者）：自动重连只恢复通信和遥测，绝不重发运行/运动命令或目标值。这里只经 connect()，
        它对外只发上位机心跳（HEARTBEAT, LEN=0）和读参（PARAM_SET 空载荷 = 只读）；不重放参数、预设、
        定时/触发发送（这些不落盘，重启即清空）。板子原来空闲就仍空闲，急停锁存仍锁存，恢复运动只能靠人。"""
        port, baud = str(rec.get("port") or ""), int(rec.get("baud") or 0) or None
        with self.lock:
            gen0 = self._gen
            self.resuming = True
        try:
            for delay in self.RESUME_TRIES:
                time.sleep(delay)
                if self._gen != gen0:
                    return {"resumed": False, "reason": "user_action"}
                try:
                    r = self.connect(port, baud)
                    self.emit({"type": "resumed", "port": port, "message": f"本地服务重启后已自动连回 {port}（急停仍锁着，确认安全后点“解除急停”）"})
                    return {"resumed": True, **r}
                except LinkError:
                    with self.lock:
                        gen0 = self._gen             # connect() 里的 disconnect() 会 +1：这是我们自己的那一次
                    continue
            ident = tuple(rec["ident"]) if rec.get("ident") else None
            moved, why = (None, "none")
            if ident and self._gen == gen0:
                moved, why = _ports.pick_moved(port, ident, rec.get("board_uid"), rec.get("schema_hash"), baud or 0)
            if moved and self._gen == gen0:
                try:
                    r = self.connect(moved, baud)
                    self.emit({"type": "port_moved", "old": port, "new": moved,
                               "message": f"本地服务重启后在 {moved} 找回了原来那块板（之前是 {port}），已经连上"})
                    return {"resumed": True, **r}
                except LinkError:
                    with self.lock:
                        gen0 = self._gen
            if self._gen != gen0:
                return {"resumed": False, "reason": "user_action"}
            self.down_reason = "port_ambiguous" if why == "ambiguous" else "port_not_found"
            lastsession.restore(rec)
            self.emit(LinkError(self.down_reason, f"本地服务重启后没能自动连回上次的板子（{port} 不在了，也没在别的口找到它）",
                                "检查 USB 线，插好后在端口列表里选一下再点“连接”").as_dict())
            return {"resumed": False, "reason": self.down_reason}
        finally:
            with self.lock:
                self.resuming = False

    # ------------------------------------------------------------------ 收
    def _locked(self, fn: Callable[[], None]) -> None:
        """在 session.lock 下做 fn；锁被别人长持时不等：排队给 dz-rxapply 线程（有排队的活时新活也排队，保证顺序）。"""
        if not self._deferred and self.lock.acquire(blocking=False):
            try:
                fn()
            finally:
                self.lock.release()
            return
        self._deferred.append(fn)
        if self._applier is None or not self._applier.is_alive():
            self._applier = threading.Thread(target=self._apply_loop, name="dz-rxapply", daemon=True)
            self._applier.start()
        self._defer_ev.set()

    def _apply_loop(self) -> None:
        while True:
            if not self._defer_ev.wait(5.0) and not self._deferred:
                return                                       # 闲 5 s 退出，下次排队再起
            self._defer_ev.clear()
            with self.lock:
                while self._deferred:
                    fn = self._deferred.popleft()
                    try:
                        fn()
                    except Exception:  # noqa: BLE001
                        pass

    def _on_bytes(self, data: bytes) -> None:
        now = time.monotonic()
        with self.rxlock:
            self.rx_bytes += len(data)
            self.last_rx = now
            self._rx_seen = True
            frames = self.parser.feed(data)
        text_mode = self.schema_hash is None and (self.schema is None or self.schema.d.get("virtual"))

        def _log(data=data, now=now):
            if self.log:
                self.log.write(RX, data)
            if self.raw_on:
                self._push_raw(now, RX, data)
        if self.log or self.raw_on:
            self._locked(_log)
        if text_mode:
            self._on_text(data, now)
        if frames:
            self.last_frame = now
        for kind, id_, seq, payload in frames:
            self.health.on_frame(seq)
            if kind == HEARTBEAT:
                self.last_hb = now
                with self.hblock:
                    self._on_heartbeat(payload)
            elif kind == DATA and id_ == ID_CMD and len(payload) == 2 and payload[0] == ord("M"):
                self.mode_ack = payload[1]
            elif kind == DATA and id_ == ID_CMD and len(payload) == 2 and payload[0] == ord("W"):
                self.save_ack = payload[1]
            elif kind == DATA and id_ == ID_CMD and len(payload) == 5 and payload[0] == ord("H"):
                self.selftest_ack = struct.unpack_from("<I", payload, 1)[0]     # 'H' 自检回包：u32 失败掩码（小端）
            elif kind == DATA and id_ == ID_RELAY and len(payload) == 1:
                self.relay_ack = payload[0]
            elif kind == DATA and id_ == ID_STEP and len(payload) in (4, 56):
                self._on_step(payload)
            elif kind == DATA and id_ == ID_REJECT and len(payload) >= 10:
                r = dzstep.decode_param_reject(payload)
                with self.step_cv:
                    self.last_reject = r
                self.emit({"type": "param_reject", **r, "ok": False, "id": r.get("index"), "reason_zh": REJECT_ZH.get(str(r.get("reason")), "板子拒绝了这次写入")})
            else:
                self._locked(lambda k=kind, i=id_, pl=payload, n=now: self._on_frame_locked(k, i, pl, n))

    def _on_heartbeat(self, payload: bytes) -> None:
        """心跳：板子身份、状态字、急停位、estop_cause。只在 hblock 下（不碰 session.lock），急停锁存不受长持锁影响。"""
        if True:
            if True:
                if len(payload) >= 4:
                    h = struct.unpack_from("<I", payload)[0]
                    if len(payload) >= 8:
                        self.board_uid = struct.unpack_from("<I", payload, 4)[0] or None
                    if not self._uid_marked:
                        self._uid_marked = True
                        lastsession.mark_board(self.port, self.board_uid, h)
                        rec = latch.get(None, self.board_uid)
                        if rec and not self.tx_locked:
                            self.tx_locked = True
                            self.estop_source = rec.get("source") or "latch_restored"
                            self.emit({"type": "tx_locked", "on": True, "source": self.estop_source, "restored": True})
                            self._pending_marks.append(("estop", "按板子身份恢复急停锁存（换了端口也保持）", self.estop_source))
                    if len(payload) >= 12:
                        self.fw_rev = struct.unpack_from("<I", payload, 8)[0] or None
                    if len(payload) < 16:
                        self._confirm_clear(0)      # 老固件心跳没有状态字（没有 bit10）：发 'R' 后下一帧心跳即视为已解除
                    if len(payload) >= 16:
                        w = struct.unpack_from("<I", payload, 12)[0]
                        if len(payload) == 32:       # 0.6.x 后续：28 字节尾 + u32 clear_t_ms（解除时的板上时刻）；40+ 字节的 28.. 是自检，不算
                            self._hb_clear_t_ms = struct.unpack_from("<I", payload, 28)[0] or None
                        self._confirm_clear(w)
                        if w != self.hb_status:
                            was = self.hb_status or 0
                            self.hb_status = w
                            m = hb_status_event(w)
                            if m:
                                self._pending_marks.append(m)
                            if w & (1 << 10) and not was & (1 << 10) and not self.tx_locked:
                                # 板子心跳急停位（car_2wd 等置 bit10）：侧车同样锁存并持久化（其他应用只报 estop_cause，下面处理）
                                self.tx_locked = True
                                self.estop_source = "firmware:estop_flag"
                                latch.set(self.port, self.board_uid, self.estop_source, "板子心跳报急停")
                                self.emit({"type": "tx_locked", "on": True, "source": self.estop_source})
                                self.emit(self.estop_ev("latched", self.estop_source, message_zh="板子心跳报急停"))
                                self._pending_marks.append(("estop", "板子心跳报急停（急停位）", self.estop_source))
                    if len(payload) >= 28:
                        es = estop_cause_dict(*struct.unpack_from("<IIf", payload, 16))
                        if len(payload) >= 40:
                            m_, t_, ph = struct.unpack_from("<III", payload, 28)
                            self.selftest, self.params_hash = selftest_dict(m_, t_), ph
                            if self.selftest is not None and (m_, t_) != self._selftest_key:   # 新的一次自检结果：记完成时间 + 当时的参数 hash
                                self._selftest_key, self.selftest_at, self.selftest_ph = (m_, t_), _iso_now(), ph
                        if es:
                            es["run_mode"] = (run_mode_dict(self.hb_status) or {}).get("mode")
                        if es and self.tx_locked and not self._cause_announced and es == self.estop_cause:
                            self.estop_cause = None          # 锁存恢复带回了同一个原因：也走下面的分支，把 cause 推给界面
                        if es is None and self.tx_locked and self.estop_cause is not None:
                            pass                     # 板子复位/重连后不再报原因：锁存期间保留已知原因，到人解除才清
                        elif es != self.estop_cause:
                            self.estop_cause = es
                            if es:
                                src = "selftest" if es["cause"] == "selftest" else "firmware:" + es["cause"]
                                es["source"] = src
                                # 不再单独推 type:"estop_cause"：cause / message_zh 只随统一事件 estop state:"latched" 下发
                                if self.estop_requested_at is not None:    # 人/Agent 发的急停：固件锁存确认
                                    self._emit_latched(self.estop_ev("latched", self.estop_source or src, cause=es["cause"], message_zh=es["message_zh"], board_t_ms=es["board_t_ms"],
                                                            latency_ms=round((time.monotonic() - self.estop_requested_at) * 1000)))
                                    self.estop_requested_at = None
                                    self._cause_announced = True
                                if self.tx_locked and self.estop_source not in (None, "firmware:estop_flag"):
                                    latch.set(self.port, self.board_uid, self.estop_source, es["message_zh"], cause=es)
                                if self.tx_locked and self.estop_source == "firmware:estop_flag":  # 急停位先到、原因后到：换成具体原因
                                    self.estop_source = src
                                    latch.set(self.port, self.board_uid, src, "板子报急停原因", cause=es)
                                    self.emit(self.estop_ev("latched", src, cause=es["cause"], message_zh=es["message_zh"], board_t_ms=es["board_t_ms"]))
                                    self._cause_announced = True
                                if not self.tx_locked:           # 板子自己急停（看门狗/堵转/欠压…）：侧车也锁存并持久化
                                    self.tx_locked = True
                                    self.estop_source = src
                                    latch.set(self.port, self.board_uid, src, es["message_zh"], cause=es)
                                    self.emit({"type": "tx_locked", "on": True, "source": src})
                                    self.emit(self.estop_ev("latched", src, cause=es["cause"], message_zh=es["message_zh"], board_t_ms=es["board_t_ms"]))
                                    self._cause_announced = True
                                if self.tx_locked and not self._cause_announced and self.estop_source not in (None, "firmware:estop_flag") \
                                        and self.estop_requested_at is None and not self._estop_hold:
                                    # 连上时板子已急停（锁存恢复，没有 bit10 上升沿）：第一帧心跳里的原因也要随 latched 推一次
                                    self.emit(self.estop_ev("latched", self.estop_source, cause=es["cause"], message_zh=es["message_zh"],
                                                            board_t_ms=es["board_t_ms"]))
                                self._cause_announced = True
                                if es["cause_id"] != 1:          # 手动急停侧车自己已记了一条（带按键来源）
                                    self._pending_marks.append(("estop", "板子急停：" + es["message_zh"], src))
                    if h != self.schema_hash and h != self._binding_h:
                        self._binding_h = h

                        def _bind(h=h):
                            try:
                                self._bind_schema(h)
                            finally:
                                self._binding_h = None
                        self._locked(_bind)

    def _on_frame_locked(self, kind: int, id_: int, payload: bytes, now: float) -> None:
        """要 session.lock 的帧（黑匣子、遥测、参数回执）：由 _locked 调用（已持锁，RLock 可重入）。"""
        if True:
            if False:
                pass
            elif kind == DATA and id_ == ID_BB and len(payload) == 16:
                t_ms, code, arg, a, b = struct.unpack("<IHHff", payload)
                with self.lock:
                    self.bb_recs.append(bb_record(t_ms, code, arg, a, b))
                    if code in (6, 7) and arg == 0:      # 参数已存进 flash / 上电用的就是 flash 里的
                        self.flash_saved_writes = self.param_writes
            elif kind == DATA and self.schema and id_ == self.schema.telem_id:
                v = self.schema.decode(payload)
                if v is not None:
                    t = v["t_ms"] / 1000.0 if "t_ms" in v else now - self.t_connect
                    with self.lock:
                        if not self.tx_locked:
                            self._sp_live = {n: float(v[n]) for n in self.setpoint_names() if n in v}
                            self._sp_frozen = False
                        self.samples.append((t, v))
                        self._new.append((t, v))
                        while self.samples and self.samples[-1][0] - self.samples[0][0] > self.history_s:
                            self.samples.popleft()
                    if self.on_sample:
                        self.on_sample(v)
            elif kind == PARAM_ACK and len(payload) >= 5:
                st, val = struct.unpack_from("<Bf", payload)
                with self.lock:
                    if self.schema and id_ < len(self.schema.params):
                        name = self.schema.params[id_]["name"]
                        val = float(round(val, 6))
                        self.params[name] = val
                        self.emit({"type": "param", "name": name, "value": val, "status": ACK_STATUS.get(st, str(st))})
                    w = self._acks.get(id_)
                if w:
                    w[1][:] = [st, val]
                    w[0].set()

    def set_framedef(self, d: dict | None) -> dict:
        """没烧工作台固件时怎么解析串口：None = key=value 文本（默认）；否则按用户帧结构（framedef.py）。"""
        try:
            p = FrameDefParser(d) if d else KvParser()
        except FrameDefError as e:
            raise LinkError("bad_framedef", str(e), "改帧结构表后再应用") from e
        with self.lock:
            self.kv = p
        return {"framedef": p.d if d else None, "fields": len(p.names) if d else 0}

    def _on_text(self, data: bytes, now: float) -> None:
        rows, grew = self.kv.feed(data)
        self.inject(rows, self.kv.schema_dict() if grew else None, "TEXT", now)

    def inject(self, rows: list[dict], schema: dict | None, tag: str, now: float | None = None) -> None:
        """虚拟通道入口（文本 key=value、ELF 变量轮询）：换 schema 时推送，样本走与 DATA 相同的管线。"""
        if self.schema_hash is not None:
            raise LinkError("busy_schema", "当前串口已绑定固件 schema，虚拟通道不能混入", "先断开串口，或改用固件遥测")
        now = time.monotonic() if now is None else now
        if not self.t_connect:
            self.t_connect = now
        if schema:
            sch = Schema(schema)
            with self.lock:
                self.schema = sch
            self.emit({"type": "schema", "schema": sch.summary() | {"hash": tag, "virtual": True}})
        if rows:
            with self.lock:
                for v in rows:
                    t = now - self.t_connect
                    self.samples.append((t, v))
                    self._new.append((t, v))
                while self.samples and self.samples[-1][0] - self.samples[0][0] > self.history_s:
                    self.samples.popleft()
            if self.on_sample:
                for v in rows:
                    self.on_sample(v)

    def _bind_schema(self, h: int) -> None:
        self.schema_hash = h
        s = find_by_hash(h)
        with self.lock:
            self.schema = s
        if s:
            self.emit({"type": "schema", "schema": s.summary()})
            threading.Thread(target=self._read_all_params_bg, daemon=True, name="read_all_params").start()
        else:
            self.emit(LinkError("schema_missing", f"板子的数据格式（哈希 {h:08X}）在本机找不到对应的 link_schema.json",
                                "在仓库根目录对这块板和应用跑一次 make（例如 make BOARD=xxx APP=car_2wd），"
                                "它会生成 build/.../linkgen/link_schema.json（打包版把它拷到 ~/.dzbench/schemas/ 或设 DZBENCH_SCHEMA_DIRS）；"
                                "若固件与工程版本不一致，重新编译烧录").as_dict())

    RAW_MAX_BYTES = 256 * 1024

    def _push_raw(self, t: float, d: int, data: bytes) -> None:
        self._raw.append((t - self.t_connect, d, data))
        self._raw_bytes += len(data)
        while self._raw_bytes > self.RAW_MAX_BYTES:      # UI 跟不上就丢最旧的，并计数
            old = self._raw.popleft()[2]
            self._raw_bytes -= len(old)
            self.raw_dropped += len(old)

    def take_raw(self, max_bytes: int = 16384) -> list:
        """取走待推送的原始块（每次最多 max_bytes，剩下的下次再推）。"""
        out, n = [], 0
        with self.lock:
            while self._raw and n < max_bytes:
                c = self._raw.popleft()
                self._raw_bytes -= len(c[2])
                out.append(c)
                n += len(c[2])
        return out

    def replay_ctl(self, seek: float | None = None, speed: float | None = None, pause: bool | None = None) -> dict:
        tr = self.tr
        if not isinstance(tr, ReplayTransport):
            raise LinkError("not_replay", "当前不是回放", "底栏选一份记录点“回放”")
        if seek is not None:
            tr.seek(seek)
            with self.lock:                       # 时间轴跳了：清掉旧样本，曲线从新位置画
                self.samples.clear()
                self._new.clear()
                self.parser = Parser()
            self.health.rebase()
        if speed is not None:
            tr.set_speed(speed)
        if pause is not None:
            tr.pause(pause)
        return {"pos": tr.position(), "len": tr.duration, "speed": tr.speed, "paused": tr.paused}

    def window_field(self, name: str, seconds: float) -> tuple[list[float], list[float]]:
        if not self.schema or name not in [f["name"] for f in self.schema.fields]:
            raise LinkError("bad_field", f"没有通道 {name}", "从下拉框选一个遥测通道")
        w = [s for s in self.window(seconds) if name in s[1]]
        return [s[0] for s in w], [float(s[1][name]) for s in w]

    def take_new(self) -> list:
        with self.lock:
            out, self._new = self._new, []
        return out

    def window(self, seconds: float) -> list:
        with self.lock:
            if not self.samples:
                return []
            t_end = self.samples[-1][0]
            return [s for s in self.samples if s[0] >= t_end - seconds]

    # ------------------------------------------------------------------ 发
    def _send(self, kind: int, id_: int, payload: bytes = b"", check: bool = False) -> bool:
        """check=True：急停锁检查与写在同一把写锁里做（急停先置 tx_locked 再拿 wlock 写急停帧，
        所以通过检查的帧一定在急停帧之前写完，不会出现“检查通过→急停→这帧照发”的竞态）。"""
        with self.lock:
            tr = self.tr
            with self.wlock:
                if check:
                    self._check_tx()
                self.seq = (self.seq + 1) & 0xFF
                frame = encode(kind, id_, self.seq, payload)
            if self.log:
                self.log.write(TX, frame)
            if self.raw_on and tr:
                self._push_raw(time.monotonic(), TX, frame)
        if not tr:
            return False
        with self.wlock:
            if check:
                self._check_tx()
            tr.write(frame)
        return True

    # 急停事件约定（docs/dev/events.md）：必有键 + 可选键；测试断言键集合精确等于约定
    ESTOP_REPLY_KEYS = {"type", "ok", "reason", "message_zh"}   # 没连板子 / 回放：不是状态事件（无 state），只提示
    # cause_zh = 只讲原因（时间线只显示它）；fix_hint_zh = 怎么解除，只在急停仍有效时（requested 送达 / latched）出现；
    # message_zh = cause_zh（+“；”+ fix_hint_zh），给旧界面兼容。
    ESTOP_EVENT_KEYS = {"requested": ({"type", "seq", "state", "source", "t", "ok", "message_zh", "cause_zh"}, {"fix_hint_zh"}),
                        "latched": ({"type", "seq", "state", "source", "t"}, {"cause", "message_zh", "cause_zh", "fix_hint_zh", "latency_ms", "board_t_ms"}),
                        "cleared": ({"type", "seq", "state", "source", "t"}, {"message_zh", "cause_zh", "latency_ms", "board_t_ms"})}

    def estop_ev(self, state: str, source: str | None, **kw) -> dict:
        """统一急停事件（与 link.state 同风格）：{type:"estop", seq, state: requested|latched|cleared, source, cause?, message_zh?, t}。"""
        kw = {k: v for k, v in kw.items() if v is not None}
        if "message_zh" in kw:
            kw.setdefault("cause_zh", kw["message_zh"])
            if state != "cleared" and kw.get("ok", True):
                kw["fix_hint_zh"] = FIX_HINT_ZH
                kw["message_zh"] = kw["cause_zh"] + "；" + FIX_HINT_ZH
        return {"type": "estop", "seq": next(self._estop_seq), "state": state, "source": source or "ui",
                "t": round(time.time() * 1000)} | kw

    def _send_estop(self, n: int = 3) -> bool:
        """急停专用通道：不拿 self.lock（别的线程长持它时急停也不排队），只拿短的写锁保证不与半帧交错；
        3 帧一次写出。写超时（串口 write_timeout 0.1 s）→ 当断线处理并如实返回 False。日志在锁空闲时补记。"""
        tr = self.tr
        if tr is None:
            return False
        with self.wlock:
            frames = b""
            for _ in range(n):
                self.seq = (self.seq + 1) & 0xFF
                frames += encode(DATA, ID_ESTOP, self.seq, b"")
            try:
                tr.write(frames)
                ok = True
            except Exception as e:  # noqa: BLE001  写超时 / 口没了
                ok = False
                err = f"急停写串口失败：{type(e).__name__}: {e}"
        if not ok:
            threading.Thread(target=self._on_transport_error, args=(err,), daemon=True).start()
        def _log():
            with self.lock:
                if self.log:
                    self.log.write(TX, frames)
                if self.raw_on:
                    self._push_raw(time.monotonic(), TX, frames)
        threading.Thread(target=_log, daemon=True).start()
        return ok

    def _emit_latched(self, ev: dict) -> None:
        """锁存确认可能比 requested 回包先到（即时心跳 ≤ 5 ms）：requested 还没广播时先压住，release 后按序补发。"""
        with self.hblock:
            if self._estop_hold:
                self._estop_held.append(ev)
                return
        self.emit(ev)

    def release_estop_events(self) -> None:
        with self.hblock:
            self._estop_hold, held, self._estop_held = False, self._estop_held, []
        for ev in held:
            self.emit(ev | {"seq": next(self._estop_seq)})   # seq 按实际下发顺序（在 requested 之后）

    def estop(self, src: str = "", hold: bool = False) -> dict:
        """急停：连发 3 帧（丢一帧也能停）。没连接时如实告知，不假装成功，也不锁存（没有板子可停，锁住只会吓到刚打开软件的人）。
        src = 谁按的（急停按钮 / Esc 键 / 空格键），写进告警文字。"""
        by = f"（{src}）" if src else ""
        if self.tr is None:
            return {"type": "estop", "ok": False, "reason": "no_board",       # 键集合见 ESTOP_REPLY_KEYS（docs/dev/events.md）
                    "message_zh": f"没连板子：急停{by}没有送达任何板子；连着真板时请直接断电/拔电池"}
        replay = isinstance(self.tr, ReplayTransport)
        with self.hblock:                  # 先记“已请求”再发：板子急停上升沿的即时心跳 ≤ 5 ms 就回来，晚记会错过锁存确认
            self.tx_locked = True
            self.estop_source = estop_source(src)
            self.estop_requested_at = None if replay else time.monotonic()
            self._estop_hold = hold            # 调用方（server）广播完 requested 再 release_estop_events()
        ok = self._send_estop(3)
        self.estop_count += 1
        if not ok:
            self.estop_requested_at = None
        if not isinstance(self.tr, ReplayTransport):
            latch.set(self.port, self.board_uid, self.estop_source, src)
        self.emit({"type": "tx_locked", "on": True, "source": self.estop_source})
        if isinstance(self.tr, ReplayTransport):
            return {"type": "estop", "ok": False, "reason": "replay", "message_zh": "回放中：急停没有送达任何板子"}
        return self.estop_ev("requested", self.estop_source, ok=ok,     # 键集合见 ESTOP_EVENT_KEYS（docs/dev/events.md）
                             message_zh=f"急停已发送{by}（3 帧）：板子已锁存" if ok else f"急停{by}没有送达！直接断电/拔电池")

    def send_data(self, id_: int, payload: bytes) -> bool:
        """发任意 DATA 帧（应用自定义命令，如 car_2wd 的 id=1 轮速设定）。0x7E/0x7F 走专用接口。"""
        self._check_tx()
        if id_ in (ID_CMD, ID_ESTOP) or not 0 <= id_ <= 0xFF or len(payload) > 64:
            raise LinkError("bad_frame", f"DATA id={id_} 长度={len(payload)} 不允许", "急停/命令请用专用按钮；payload ≤ 64 字节")
        return self._send(DATA, id_, payload, check=True)

    def blackbox(self, wait_s: float = 0.6) -> list[dict]:
        """请求板子导出黑匣子（dzctl 0.6.0 DATA 0x7D len=0），收 wait_s 秒。只读，急停锁存时也允许（事后查原因正需要）。"""
        with self.lock:
            self.bb_recs = []
        if not self._send(DATA, ID_BB):
            raise LinkError("not_connected", "没连板子", "")
        time.sleep(wait_s)
        with self.lock:
            return list(self.bb_recs)

    SAVE_STATUS = {0: "参数已写入 flash：下次上电自动加载", 1: "电机没停稳：为安全起见没写（停车或急停后再存）",
                   2: "这块板子没有可用的 flash 存储区（board.yaml mcu.nvm_kb 为 0）", 3: "flash 写入失败（重试；反复失败说明存储区坏了）"}

    def save_params(self, wait_s: float = 1.5) -> dict:
        """dzctl 0.8.0：把板上当前参数一次写进 flash（'W'），等板子回执 {'W', 结果}。旧固件不回执 → ok=None。"""
        self._check_tx()
        self.save_ack = None
        if not self._send(DATA, ID_CMD, b"W", check=True):
            raise LinkError("not_connected", "没连板子", "")
        t_end = time.monotonic() + wait_s
        while time.monotonic() < t_end and getattr(self, "save_ack", None) is None:
            time.sleep(0.01)
        a = getattr(self, "save_ack", None)
        if a is None:
            return {"ok": None, "result": None, "message_zh": "板子没回执（固件早于 dzctl 0.8.0？）：用黑匣子看“参数已存”记录"}
        self.mark("param", self.SAVE_STATUS.get(a, f"保存结果 #{a}"))
        return {"ok": a == 0, "result": a, "message_zh": self.SAVE_STATUS.get(a, f"保存结果 #{a}")}

    MODE_STATUS = {0: "运行模式已切换并写入 flash（下次上电仍是这个模式）", 1: "电机没停稳：为安全起见没切（停车或急停后再切）",
                   2: "这块板子没有可用的 flash 存储区：模式存不下，没切", 3: "flash 写入失败，没切", 4: "缺少确认字节或模式非法：没切"}
    MODE_MAGIC = 0xA5

    def set_run_mode(self, mode: str, confirmed: bool = False, wait_s: float = 1.5) -> dict:
        """dzctl 0.10.0：切联机/脱机。只能由人发起——界面先弹确认卡，用户点确认后才带 confirmed=True 调用；
        没确认就不发（板子那边也要确认字节，缺了拒切）。"""
        if mode not in ("tethered", "standalone"):
            raise ValueError(f"mode 只能是 tethered / standalone，收到 {mode!r}")
        from .human_only import require_confirmed
        nc = require_confirmed(confirmed, "切换运行模式需要确认：" + ("脱机后板子不再要求上位机心跳，只靠板上保护" if mode == "standalone" else "联机后上位机断线会急停"))
        if nc:
            return nc
        self._check_tx()
        self.mode_ack = None
        if not self._send(DATA, ID_CMD, bytes([ord("M"), 1 if mode == "standalone" else 0, self.MODE_MAGIC]), check=True):
            raise LinkError("not_connected", "没连板子", "")
        t_end = time.monotonic() + wait_s
        while time.monotonic() < t_end and getattr(self, "mode_ack", None) is None:
            time.sleep(0.01)
        a = getattr(self, "mode_ack", None)
        if a is None:
            return {"ok": None, "result": None, "message_zh": "板子没回执（固件早于 dzctl 0.10.0？）"}
        msg = self.MODE_STATUS.get(a, f"切换结果 #{a}")
        self.mark("param", ("运行模式 → " + ("脱机" if mode == "standalone" else "联机") + "：" if a == 0 else "运行模式没切：") + msg)
        return {"ok": a == 0, "result": a, "message_zh": msg}

    def run_selftest(self, wait_s: float = 1.5) -> dict:
        """dzctl 0.12.0：让板子重跑全部自检（'H'），等回执 {'H', u32 fail_mask}。旧固件不回执 → ok=None。"""
        self._check_tx()
        self.selftest_ack = None
        if not self._send(DATA, ID_CMD, b"H", check=True):
            raise LinkError("not_connected", "没连板子", "")
        t_end = time.monotonic() + wait_s
        while time.monotonic() < t_end and getattr(self, "selftest_ack", None) is None:
            time.sleep(0.01)
        m = getattr(self, "selftest_ack", None)
        if m is not None:
            self.h_supported = True                # 这块板子认 'H'：以后没回就是超时，而不是旧固件
        if m is None:
            return {"ok": None, "mask": None, "failed_items": [], "message_zh": "板子没回执（固件早于 dzctl 0.12.0？）"}
        d = selftest_dict(m, 1)
        with self.hblock:                        # 'H' 回包也是一次完成的自检
            self.selftest_at, self.selftest_ph = _iso_now(), self.params_hash
        msg = "自检全部通过" if d["pass"] else "自检没通过：" + "；".join(i["message_zh"] for i in d["failed_items"])
        self.mark("param", msg)
        return {"ok": d["pass"], "mask": m, "failed_items": d["failed_items"], "message_zh": msg}

    RELAY_STATUS = {0: "ok", 1: "参数非法或板上没有这个 PID 回路", 2: "板子急停中"}

    def relay(self, loop: int, amp: float, hyst: float, timeout_s: float, wait_s: float = 0.5) -> dict:
        """让板上第 loop 个 PID 的输出换成继电器 ±amp（滞环 hyst，timeout_s 后板子自己恢复），等板子回执。"""
        self._check_tx()
        self.relay_ack = None
        if not self._send(DATA, ID_RELAY, struct.pack("<Bfff", loop, amp, hyst, timeout_s), check=True):
            raise LinkError("not_connected", "没连板子", "")
        t_end = time.monotonic() + wait_s
        while time.monotonic() < t_end and getattr(self, "relay_ack", None) is None:
            time.sleep(0.01)
        a = getattr(self, "relay_ack", None)
        return {"ok": a == 0, "status": a, "why": "板子没回执（固件早于 dzctl 0.7.0？）" if a is None else self.RELAY_STATUS.get(a, str(a))}

    # ------------------------------------------------------------ #38 阶跃实验（dzctl 0.13.0 DATA 0x7B）
    STEP_ACK_ZH = {"bad_arg": "开始帧参数不对（通道 / 时长 200–30000 ms）", "estop": "板子急停中", "busy": "板上已有阶跃实验在跑",
                   "unsupported": "这个应用没配阶跃通道（app.yaml link.step）", "offline": "板子在脱机模式"}

    iter_owner: threading.Thread | None = None   # #70：整个自动迭代期间（含两轮之间）由跑迭代的线程持有

    def iter_busy(self) -> bool:
        """心跳 bit17 DZCTL_HB_ITER_BUSY（板上阶跃实验进行中），或别的线程正在跑自动迭代（#70：bit17 只盖住一次阶跃，
        两轮之间的空档也不许界面改设定值 / 参数）。跑迭代的线程自己不算 busy。"""
        w = self.hb_status
        if w is not None and w & HB_ITER_BUSY:
            return True
        o = self.iter_owner
        return bool(o is not None and o.is_alive() and o is not threading.current_thread())

    def iter_hold(self):
        """with s.iter_hold(): …  —— 迭代全程把 busy 交给当前线程。"""
        import contextlib

        @contextlib.contextmanager
        def cm():
            prev, self.iter_owner = self.iter_owner, threading.current_thread()
            try:
                yield
            finally:
                self.iter_owner = prev
        return cm()

    def _on_step(self, payload: bytes) -> None:
        with self.step_cv:
            if len(payload) == 4:
                self.step_ack = dzstep.decode_step_ack(payload)
            else:
                r = dzstep.decode_step_result(payload)
                self.step_results.append(r)
                del self.step_results[:-16]
            self.step_cv.notify_all()
        if len(payload) == 56:
            # #54：固件发 step_result 的同一拍就清了 bit17；本地心跳状态要到下一帧心跳（~500 ms）才更新。
            # 收到结果即按固件真相清掉本地 bit17，迭代引擎下一轮写参数不会被自己这一步的“忙”挡住；
            # 别人（界面/另一个进程）新开的阶跃会在之后的心跳里重新置位，照样挡。
            with self.hblock:
                if self.hb_status is not None:
                    self.hb_status &= ~HB_ITER_BUSY
            self.emit({"type": "step_result", **self.step_results[-1]})

    def step_start(self, ch: int, it: int, target: float, dur_ms: int, wait_s: float = 0.5) -> dict:
        """开始一轮板上阶跃（12 B：ch, 0, iter, target, dur_ms）。急停中 / 板子不支持等直接报错。"""
        import math
        if not 200 <= int(dur_ms) <= 30000 or not math.isfinite(float(target)):
            raise LinkError("bad_step", f"阶跃参数不对：dur_ms={dur_ms} target={target}", "dur_ms 200–30000，target 是有限数")
        with self.step_cv:
            self.step_ack = None
        if not self._send(DATA, ID_STEP, dzstep.encode_step_start(int(ch), int(it), float(target), int(dur_ms)), check=True):
            raise LinkError("not_connected", "没连板子", "")
        t_end = time.monotonic() + wait_s
        with self.step_cv:
            while self.step_ack is None and time.monotonic() < t_end:
                self.step_cv.wait(0.02)
            a = self.step_ack
        if a is None:
            raise LinkError("step_no_ack", "板子没回阶跃应答（固件早于 dzctl 0.13.0？）", "升级固件后重试")
        if a["status"] != "started":
            est = a["status"] == "estop"
            raise LinkError("step_" + str(a["status"]), self.STEP_ACK_ZH.get(a["status"], f"阶跃被拒 {a['status']}"),
                            "确认安全后在界面点“解除急停”" if est else "", "estop_clear" if est else None, {"ack": a})
        return a

    def step_wait(self, it: int, timeout: float) -> dict | None:
        """等 iter = it 的 step_result（开始之后到的那一帧）。"""
        t_end = time.monotonic() + timeout
        with self.step_cv:
            while time.monotonic() < t_end:
                r = next((x for x in reversed(self.step_results) if x["iter"] == it), None)
                if r is not None:
                    self.step_results.remove(r)
                    return r
                self.step_cv.wait(0.05)
        return None

    def step_stop(self) -> bool:
        """空载荷 = 停止（板子发 aborted、cause 0x80 的结果）。急停中也能发（停止只会更安全）。"""
        return self._send(DATA, ID_STEP)

    def relay_stop(self) -> bool:
        return self._send(DATA, ID_RELAY)

    def cmd(self, c: str, n: int | None = None) -> bool:
        # 人按了“解除急停”（界面；Agent 不能发 R）。不提前解锁、不提前宣告：等固件心跳 bit10 清零（_confirm_clear）。
        # clear_pending_at 必须在 _send 之前置位：固件对 bit10 下降沿会立刻回一帧心跳，晚置会漏掉那一帧、白等下一周期（~500 ms）。
        no_hb = False
        if c == "R":
            with self.hblock:
                if self.tx_locked:
                    self.clear_pending_at = time.monotonic()
                    no_hb = not self.last_hb          # 从没收到过工作台心跳（非工作台固件 / 文本设备）
        ok = self._send(DATA, ID_CMD, c.encode()[:1] + (bytes([n]) if n is not None else b""))
        if c == "R":
            with self.hblock:
                if not ok:
                    self.clear_pending_at = None      # 没发出去就取消等待
                elif no_hb:
                    self._confirm_clear(0)            # 没有 bit10 可等，R 发出即解除
        return ok

    def _confirm_clear(self, w: int) -> None:
        """心跳处理里调用（持 hblock）：发过 'R' 之后第一帧 bit10=0 的心跳才算固件已解除 → 解锁、清持久化、推 cleared。"""
        if self.clear_pending_at is None or w & (1 << 10):
            return
        ms = round((time.monotonic() - self.clear_pending_at) * 1000)
        self.clear_pending_at = None
        latch.clear(self.port, self.board_uid)
        if self.tx_locked and not self._sp_frozen:
            self._freeze_sp()
        was, self.tx_locked, self.estop_source = self.tx_locked, False, None
        self.estop_cause = None
        if was:
            self.emit({"type": "tx_locked", "on": False})
            kw = {"board_t_ms": self._hb_clear_t_ms} if self._hb_clear_t_ms else {}   # 32 字节心跳才有 clear_t_ms
            self.emit(self.estop_ev("cleared", "ui", message_zh="已由人工解除急停", latency_ms=ms, **kw))

    def setpoint_names(self) -> list[str]:
        """设定值槽位（DATA id=1 第 i 个 f32）= 遥测里带 ref_for 的字段，按出现顺序（与 gen_link link.step.sp 同口径）。"""
        if not self.schema:
            return []
        return [f["name"] for f in self.schema.fields if f.get("ref_for")]

    def _primary_sp(self) -> str | None:
        names = self.setpoint_names()
        st = self.schema.step if self.schema else []
        i = int(st[0].get("sp", 0)) if st else 0
        return names[i] if 0 <= i < len(names) else (names[0] if names else None)

    def _freeze_sp(self) -> None:
        """锁存那一刻冻结急停前主设定值（固件锁存时把设定值清零，所以取锁存前最后一帧遥测）。"""
        n = self._primary_sp()
        self.sp_before_latch = self._sp_live.get(n) if n else None
        self._sp_frozen = True

    def setpoint_set(self, name: str, raw) -> dict:
        """只下发设定值（DATA id=1），不跑阶跃实验。急停中拒绝；按 link_schema 校验，不合法 invalid_param，从不钳位。
        其他槽位保持遥测里的当前值。成功后清 sp_before_latch。"""
        from .schema import _invalid, check_value
        if self.tx_locked:
            raise LinkError("estop_locked", "急停中不下发目标", "确认安全后在界面点“解除急停”，再下发目标", "estop_clear", {"reason": "state"})
        if self.iter_busy():
            raise LinkError("iter_busy", "阶跃实验进行中，结束或停止后再设定目标", "等这一轮结束或点“停止迭代”", "stop_iteration",
                            {"ok": False, "reason": "busy", "message_zh": "阶跃实验进行中，结束或停止后再设定目标",
                             "reason_zh": "自动迭代进行中，结束或停止后再设定目标"})
        names = self.setpoint_names()
        if name not in names:
            raise _invalid(name, f"不是设定值（可选：{'、'.join(names) or '无'}）", None, "name")
        hold = next(c["hold"] for c in self.schema.setpoints() if c["name"] == name)
        if hold != "latched":
            raise LinkError("hold_timeout", "这块板子的目标不会保持，重新开始实验即可", "重新开始实验（阶跃 / 迭代）", "restart_experiment",
                            {"reason": "hold", "hold": hold, "message_zh": "这块板子的目标不会保持，重新开始实验即可"})
        v = check_value(name, raw, None)
        slot = names.index(name)
        rng = next((float(c["range"]) for c in (self.schema.step or []) if int(c.get("sp", -1)) == slot and c.get("range") is not None), None)
        if rng is not None and abs(v) > rng:
            raise _invalid(name, f"超出范围（|值| ≤ {rng:g}，link.step.range）", None, "range")
        with self.lock:
            vals = [float(self._sp_live.get(n, 0.0)) for n in names]
        vals[slot] = v
        if not self.send_data(1, struct.pack(f"<{len(vals)}f", *vals)):
            raise LinkError("not_connected", "没连板子", "")
        with self.lock:
            self._sp_live[name] = v
            self.sp_before_latch, self._sp_frozen = None, False
        return {"name": name, "value": v, "slot": slot}

    def _check_tx(self) -> None:
        if self.tx_locked:
            raise LinkError("tx_locked", "急停后本地服务的预设/定时/触发/原始发送已全部停用", "确认安全后点“解除急停”")

    def send_raw(self, data: bytes) -> bool:
        """原样发字节（给非工作台固件的设备，如 AT 指令）。急停后拒绝。"""
        self._check_tx()
        if len(data) > 1024:
            raise LinkError("bad_frame", "一次最多发 1024 字节")
        with self.lock:
            tr = self.tr
            if self.log:
                self.log.write(TX, data)
            if self.raw_on and tr:
                self._push_raw(time.monotonic(), TX, data)
        if not tr:
            return False
        with self.wlock:
            self._check_tx()                     # 同一把写锁里再查一次（见 _send）
            tr.write(data)
        return True

    def _param_rpc(self, name: str, payload: bytes, retries: int = 3, timeout: float = 0.25) -> tuple[float, str]:
        if not self.schema:
            raise LinkError("no_schema", "还没识别出板子的参数表", "等一两秒收到心跳；仍不行看上面的 schema 提示")
        if name not in self.schema.param_index:
            raise LinkError("bad_param", f"没有参数 {name}")
        i = self.schema.param_index[name]
        ev, box = threading.Event(), []
        with self.lock:
            self._acks[i] = (ev, box)
        try:
            for _ in range(retries):
                ev.clear()
                if not self._send(PARAM_SET, i, payload):
                    raise LinkError("not_connected", "未连接", "先连接板子")
                if ev.wait(timeout):
                    return box[1], ACK_STATUS.get(box[0], str(box[0]))
            raise LinkError("ack_timeout", f"参数 {name} 写入没有回应（重发 {retries} 次）",
                            "板子可能卡死/复位/没跑工作台固件；看心跳灯是否还在闪")
        finally:
            with self.lock:
                self._acks.pop(i, None)

    def set_param(self, name: str, value: float, verify: bool = False) -> dict:
        """verify=True：写完再单独读一次，和 ACK 报的生效值比对（llm-pid-tuner 的“回读比对”，MIT）。
        Agent 落地参数、恢复快照时用；拖滑条不用（多一次往返）。"""
        sch = self.schema
        # #40/#38：按 link_schema.json 校验（范围、类型、单步 max_delta），不合法直接 invalid_param，从不钳位
        v = sch.check(name, value, self.params.get(name)) if sch else check_value(name, value)
        if self.tx_locked:
            raise LinkError("param_locked", "急停中不写参数", "确认安全后点“解除急停”再改", "estop_clear",
                            {"ok": False, "name": name, "id": sch.param_index.get(name) if sch else None, "reason": "state", "reason_zh": "急停中，参数已锁定"})
        pid = sch.param_index.get(name) if sch else None
        if self.iter_busy():                      # #71：带 ok:false、reason、reason_zh、参数 id，界面标在对应参数行上
            raise LinkError("param_locked", "自动迭代进行中，参数已锁定", "等迭代结束或点“停止迭代”", "stop_iteration",
                            {"ok": False, "name": name, "id": pid, "reason": "busy", "reason_zh": REJECT_ZH["busy"]})
        with self.step_cv:
            self.last_reject = None
        applied, status = self._param_rpc(name, struct.pack("<f", v))
        self.param_writes += 1
        out = {"ok": status != "rejected", "name": name, "id": pid, "requested": v, "applied": applied, "status": status}
        if status == "rejected":                  # 板子拒绝（0.13.0）：PARAM_ACK 5 + param_reject 帧
            t_end = time.monotonic() + 0.1
            with self.step_cv:
                while self.last_reject is None and time.monotonic() < t_end:
                    self.step_cv.wait(0.02)
                rj = self.last_reject
            out["reason"] = (rj or {}).get("reason") or "unknown"
            out["reason_zh"] = REJECT_ZH.get(str(out["reason"]), "板子拒绝了这次写入")
            return out
        if verify:
            rb = self.read_param(name)
            out["readback"] = rb
            if abs(rb - applied) > 1e-6 * max(1.0, abs(applied)):
                raise LinkError("readback_mismatch", f"{name} 写入后板上回报 {applied}，回读却是 {rb}",
                                "可能固件里别处也在改这个变量（例如自整定/状态机），或写入被覆盖；先看固件逻辑再重试")
        return out

    def read_param(self, name: str) -> float:
        return self._param_rpc(name, b"")[0]

    def read_all_params(self) -> dict:
        out = {}
        schema = self.schema                      # 快照：断开/换板时 self.schema 可能被别的线程置 None
        for p in (schema.params if schema else []):
            try:
                out[p["name"]] = self.read_param(p["name"])
            except LinkError:
                break
        return out

    def _read_all_params_bg(self) -> None:
        """识别出 schema 后的后台读参。断开/关串口时 _send 可能抛 OSError/ValueError 等，
        后台线程里不能让异常逃逸（否则 PytestUnhandledThreadExceptionWarning，打包版里是静默丢线程）。"""
        try:
            self.read_all_params()
        except Exception as e:  # noqa: BLE001
            self.emit(LinkError("param_read_aborted", f"后台读参数中断：{type(e).__name__}: {e}",
                                "通常是读参途中断开/换口；重新连接后会自动再读").as_dict())

    def export_readback(self, path: str | pathlib.Path) -> str:
        """参数全量回读（逐个问板子，不是上位机记的值）写成 params.txt，给 tools/params_diff.py 和 docs/verify 用。"""
        if not self.schema:
            raise LinkError("no_schema", "还没识别出参数表，不能回读")
        vals = self.read_all_params()
        if len(vals) < len(self.schema.params):
            raise LinkError("readback_incomplete", f"只读回 {len(vals)}/{len(self.schema.params)} 个参数", "检查连接后重试")
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(readback_text(vals, self.schema.hash, self.fw_rev, self.board_uid), encoding="utf-8", newline="\n")
        return str(p)

    # ------------------------------------------------------------------ 快照 / 日志
    def snapshot_save(self, name: str, note: str = "", mode: str = "") -> str:
        if not self.schema:
            raise LinkError("no_schema", "还没识别出参数表，不能存快照")
        if mode not in snapshots.MODES:
            raise LinkError("bad_mode", f"环模式只能是 {'/'.join(m for m in snapshots.MODES if m)} 或留空")
        return str(snapshots.save(self.schema.hash, name, dict(self.params), note, mode))

    RAMP_DT = 0.05

    def snapshot_restore(self, name: str | None = None, defaults: bool = False, ramp_s: float = 0.0) -> list[dict]:
        """ramp_s > 0：平滑切换（速度环 ↔ 位置环预设），每 RAMP_DT 秒一步线性过渡，最后一步回读校验；
        中途急停 / 断线（set_param 抛错）立刻停在当前步，不再继续写。"""
        if not self.schema:
            raise LinkError("no_schema", "还没识别出参数表")
        vals = {p["name"]: p["default"] for p in self.schema.params} if defaults else snapshots.load(self.schema.hash, name)
        vals = {k: v for k, v in vals.items() if k in self.schema.param_index}
        ramp_s = max(0.0, min(float(ramp_s or 0.0), 10.0))
        if ramp_s <= 0:
            return [self.set_param(k, v, verify=True) for k, v in vals.items()]
        plan = snapshots.ramp_plan({k: self.params.get(k) for k in vals}, vals, max(1, round(ramp_s / self.RAMP_DT)))
        out, e0 = {}, self.estop_count
        for i, st in enumerate(plan):
            if self.estop_count != e0:
                raise LinkError("ramp_aborted", f"平滑切换第 {i}/{len(plan)} 步遇到急停，已停止写参数", "确认安全后重新恢复快照")
            last = i == len(plan) - 1
            for k, v in st.items():
                out[k] = self.set_param(k, v, verify=last)
            if not last:
                time.sleep(self.RAMP_DT)
        return list(out.values())

    def start_log(self) -> str:
        tag = re.sub(r"[^0-9A-Za-z_+-]+", "-", (self.port or "").split("/")[-1]).strip("-")[:40]   # 文件名带上端口/仿真应用，回放列表里认得出
        name = time.strftime("run_%Y%m%d_%H%M%S") + (f"_{tag}" if tag else "") + ".dzlog"
        self.log = LogWriter(self.log_dir / name, {"port": self.port, "baud": self.baud,
                                                   "start": time.strftime("%Y-%m-%d %H:%M:%S"),
                                                   "schema_hash": f"{self.schema_hash:08X}" if self.schema_hash else None})
        return str(self.log.path)

    # ------------------------------------------------------------------ 状态
    def _times_locked(self, now: float) -> tuple[float | None, float | None]:
        """(dzlog 时间, 曲线时间)：回放 = 回放位置；实时在记录 = 距记录开头；曲线时间 = 最新样本的 t。"""
        log_t = (self.tr.position() if isinstance(self.tr, ReplayTransport)
                 else now - self.log.t0 if self.log else None)
        return log_t, (self.samples[-1][0] if self.samples else None)

    def mark(self, kind: str, text: str, source: str | None = None) -> dict:
        """往事件时间线记一条（带两种时间）并广播。estop / watchdog 一律带 source（不允许“来源未知”）。"""
        if kind in ("estop", "watchdog") and not source:
            source = self.estop_source or ("heartbeat_lost" if kind == "watchdog" else "sidecar")
        # 事件循环里也会调 mark：别的线程长持 self.lock 时不等，时间戳留空也要先把事件推出去
        now = time.monotonic()
        if self.lock.acquire(blocking=False):
            try:
                log_t, plot_t = self._times_locked(now)
            finally:
                self.lock.release()
        else:
            log_t, plot_t = None, None
        e = self.timeline.add(kind, text, log_t, plot_t, source)
        self.emit(e)
        return e

    def link_state(self, now: float | None = None) -> dict | None:
        """唯一的连接状态（见 linkstate.py）；变化或到保活间隔时返回一条 link.state，否则 None。"""
        now = time.monotonic() if now is None else now
        fw = self.fw_status()
        with self.linklock:                    # 不拿 session.lock：长持锁时 link.state 照推（读的都是单个属性）
            return self.link.update(now, port=self.port, port_open=self.tr is not None,
                                    reconnecting=self.reconnecting or (self.resuming and self.tr is None), t_connect=self._t_tr,
                                    last_frame=self.last_frame,
                                    reason="resuming" if self.resuming and self.tr is None else self.down_reason,
                                    mode=(run_mode_dict(self.hb_status) or {}).get("mode") or self.run_mode,
                                    fw=fw)

    def selftest_snapshot(self) -> dict | None:
        """selftest 快照 + at（完成时间 ISO）+ params_hash_at（自检时参数 hash）+ stale（参数已变 → 封箱页提示重新自检）。"""
        if self.selftest is None:
            return None
        ph_at = self.selftest_ph
        return dict(self.selftest) | {"at": self.selftest_at,
                                      "params_hash_at": None if ph_at is None else f"{ph_at:08x}",
                                      "stale": ph_at is not None and self.params_hash is not None and ph_at != self.params_hash}

    def _estop_cause_view(self) -> dict | None:
        """estop_cause 快照：急停仍锁着才带 fix_hint_zh（怎么解除）；解除后 estop_cause 已清空。"""
        es = self.estop_cause
        if es is None:
            return None
        return dict(es) | ({"fix_hint_zh": FIX_HINT_ZH} if self.tx_locked else {})

    def fw_status(self) -> dict:
        """固件上报的板上状态快照（link.state / progress 共用，字段名与固件一致）；没上报 = null。
        由 hblock 保护（与收线程心跳处理同一把小锁），不拿 session.lock。"""
        with self.hblock:
            hb = self.hb_status
            return {"run_mode": run_mode_dict(hb), "selftest": self.selftest_snapshot(),
                    "params_saved": None if self.params_hash is None or hb is None else not (hb & (1 << 16)),
                    "params_hash": None if self.params_hash is None else f"{self.params_hash:08x}",
                    "estop_cause": self._estop_cause_view()}

    def status(self) -> dict:
        now = time.monotonic()
        with self.lock:
            connected = self.tr is not None or self.reconnecting
            alive = connected and now - self.last_frame <= HB_TIMEOUT_S
            st = {"type": "status", "connected": connected, "port": self.port, "baud": self.baud,
                  "alive": alive, "rx_bytes": self.rx_bytes, "good": self.parser.good, "bad": self.parser.bad,
                  "schema": f"{self.schema_hash:08X}" if self.schema_hash is not None else None,
                  "schema_ok": self.schema is not None, "fw_rev": fw_rev_str(self.fw_rev) if self.fw_rev else None, "log": str(self.log.path) if self.log else None,
                  "replay": isinstance(self.tr, ReplayTransport),
                  "reconnecting": self.reconnecting, "tx_locked": self.tx_locked, "reconnects": self.reconnects, "reconnect_attempt": self.reconnect_attempt, "stall_s": self.stall_s, "raw_dropped": self.raw_dropped,
                  "replay_progress": self.tr.progress() if isinstance(self.tr, ReplayTransport) else None}
            if isinstance(self.tr, ReplayTransport):
                st.update(replay_pos=round(self.tr.position(), 2), replay_len=round(self.tr.duration, 2),
                          replay_speed=self.tr.speed, replay_paused=self.tr.paused)
            marks, self._pending_marks = list(self._pending_marks), []
            st.update(hb_status_dict(self.hb_status))
            st["estop_cause"] = self._estop_cause_view()
            if self.tx_locked and not self._sp_frozen:
                self._freeze_sp()
            st["sp_before_latch"] = self.sp_before_latch
            st["setpoints"] = self.schema.setpoints() if self.schema else []   # [{name, slot, ref_for, hold}]，hold 原样透传，缺省 timeout
            st["run_mode"] = run_mode_dict(self.hb_status)
            st["selftest"] = self.selftest_snapshot()
            st["params_saved"] = None if self.params_hash is None or self.hb_status is None else not (self.hb_status & (1 << 16))
            st["params_hash"] = None if self.params_hash is None else f"{self.params_hash:08x}"
            if self.tr is not None:
                log_t, plot_t = self._times_locked(now)
                hist = self.health.history()
                st["hb"] = self.health.tick(now, self.parser.good, self.parser.bad, self.rx_bytes, log_t, plot_t)
                marks += [("crc", f"CRC 坏帧突增：1 秒 {c['crc']} 帧") for c in st["hb"] if crc_spike(c, hist)]
                if self._was_alive and not alive and not self.reconnecting:
                    marks.append(("watchdog", f"{HB_TIMEOUT_S} s 没收到板子心跳（板端看门狗应已急停）", "heartbeat_lost"))
            self._was_alive = alive
        for mk in marks:
            self.mark(*mk)
        if self.reconnecting:
            st["hint"] = "连接断开，正在自动重连…（线插回去即可；急停此时送不到板子，板子 1 秒没收到心跳会自己急停）"
        elif connected and self.parser.good >= 20 and self.parser.bad * 10 > self.parser.good:
            st["hint"] = (f"坏帧偏多（{self.parser.bad} 坏 / {self.parser.good} 好）：线上有干扰或乱码。"
                          "检查共地、杜邦线长度、电机线是否和串口线捆在一起；数据仍按校验通过的帧显示")
        elif connected and not alive and now - self.t_connect > HB_TIMEOUT_S:
            st["hint"] = ("收到字节但没有合法帧：波特率可能不对" if self.rx_bytes and not self.parser.good
                          else f"超过 {HB_TIMEOUT_S:g} s 没有合法帧：板子没上电/没跑工作台固件/线松了")
        return st


ID_BB = 0x7D
ID_RELAY = 0x7C   # dzctl 0.7.0 继电自整定（固件 pid_relay_*）
BB_NAMES = {1: "上电", 2: "堵转", 3: "急停", 4: "人工解除", 5: "丢线", 6: "参数存 flash", 7: "上电读参数", 8: "上次运行记录"}


def bb_record(t_ms: int, code: int, arg: int, a: float, b: float) -> dict:
    """黑匣子一条 → 人话（码见 firmware/framework/blackbox BB_EV_*；≥0x100 是应用自定义）。"""
    if code == 1:
        text = f"上电，复位原因：{RESET_NAMES.get(arg, f'#{arg}')}"
    elif code == 2:
        text = f"第 {arg} 路堵转（负载 {a:.3g}，转速 {b:.3g}）"
    elif code == 4:
        text = "人工解除" + (f"（之前堵转通道位图 {arg:#x}）" if arg else "")
    elif code == 5:
        text = f"丢线（阶段 {arg}，最后线位置 {a:.3g}）"
    elif code == 6:
        text = "参数已存进 flash" if arg == 0 else f"参数存 flash 失败（错误 {arg}）"
    elif code == 7:
        text = "上电读参数：" + {0: "用了 flash 里存的", 1: "没存过，用默认值", 2: "结构变了或越界，用默认值", 3: "这块板没有存储，用默认值"}.get(arg, f"#{arg}")
    elif code == 8:
        text = f"——以下 {arg} 条是上次运行冻结的记录——"
    else:
        text = f"{BB_NAMES.get(code, f'应用事件 {code:#x}')} arg={arg} a={a:.3g} b={b:.3g}"
    return {"t_ms": t_ms, "code": code, "arg": arg, "a": a, "b": b, "text": text}


RESET_NAMES = {0: "未知", 1: "上电", 2: "复位键", 3: "欠压", 4: "看门狗", 5: "软件复位", 6: "内核锁死"}
HB_FLAGS = {1 << 8: "安全态", 1 << 9: "堵转", 1 << 10: "急停", 1 << 11: "自检失败", 1 << 14: "脱机模式", 1 << 15: "脱机运行中", 1 << 16: "参数未保存", 1 << 17: "迭代中"}


# dzctl 0.11.0 dzctl_selftest_item_t（0.12.0 起应用可注册 6..32 的自定义项）：心跳 selftest_mask 的 bit (code−1)
SELFTEST_ITEMS = {1: ("subsys", "子系统自检没通过（某个子系统的 selftest 返回失败）"),
                  2: ("params", "参数越界或非法（已按默认值运行前请检查参数表）"),
                  3: ("nvm", "flash 存储区不可用：参数存不下，掉电后恢复默认"),
                  4: ("sensor", "传感器无数据（编码器 / 视觉 / IMU）"),
                  5: ("power", "电源电压不在允许范围")}


def _iso_now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def selftest_dict(mask: int, t_ms: int) -> dict | None:
    """心跳 u32 selftest_mask, u32 t_ms → {pass, failed_items:[{code,key,message_zh}], t}；t_ms = 0（应用没报）→ None。"""
    if not t_ms:
        return None
    items = []
    for b in range(32):
        if mask & (1 << b):
            k, msg = SELFTEST_ITEMS.get(b + 1, (f"item_{b + 1}", f"自检项 #{b + 1} 没通过"))
            items.append({"code": b + 1, "key": k, "message_zh": msg})
    return {"pass": not items, "failed_items": items, "t": round(t_ms / 1000.0, 3)}


def run_mode_dict(w: int | None) -> dict | None:
    """dzctl 0.10.0 心跳 bit14/15 → {mode: "tethered"|"standalone", started, label_zh}；旧固件（没 status 字）→ None。"""
    if w is None:
        return None
    sa = bool(w & (1 << 14))
    started = sa and bool(w & (1 << 15))
    return {"mode": "standalone" if sa else "tethered", "started": started,
            "label_zh": ("脱机（运行中）" if started else "脱机（待启动：板上按键短按）") if sa else "联机（上位机给目标，心跳丢失急停）"}


# dzctl 0.8.0 dzctl_estop_cause_t → (cause 键, 中文说明模板)。{v} = 触发值，{t} = 板上时刻 s。
ESTOP_CAUSES = {
    1: ("manual", "手动急停：上位机发出急停指令（急停按钮 / Esc / 空格）"),
    2: ("hb_timeout", "心跳超时 {v:.0f} ms"),          # 详情放 detail_zh；阈值归固件 apps/include/link_app.h dzctl_wd_init(1000)
    3: ("stall", "电机堵转：输出 {v:.2f} 时转速持续接近 0，已刹车保护"),
    4: ("undervolt", "电池欠压：电压 {v:.2f} V 低于临界值，已停机（电压回升也不会自动恢复）"),
    5: ("overcurrent", "过流：电流 {v:.2f} A 超过上限，已切断输出"),
    6: ("limit", "限位 / 超量程：{v:.3g} 超出允许范围，已停机"),
    7: ("selftest", "上电自检失败：{v:.0f} 项未通过，输出保持关闭"),
    8: ("safe_boot", "异常复位后进入安全态：复位原因 {r}，输出保持关闭"),
    9: ("sensor", "传感器读取失败（资源 {v:.0f}），已故障停机"),
}


FIX_HINT_ZH = "确认安全后点“解除急停”"


def estop_cause_dict(cause: int, t_ms: int, value: float) -> dict | None:
    """心跳尾部 u32 cause, u32 t_ms, f32 value → {cause, cause_id, message_zh, value, t}；cause 0 → None。"""
    if not cause:
        return None
    key, tpl = ESTOP_CAUSES.get(cause, (f"unknown_{cause}", "未知急停原因 #{c}"))
    msg = tpl.format(v=value, c=cause, r=RESET_NAMES.get(int(value), f"#{int(value)}"))
    extra = {"fix_action": "estop_clear", "gap_ms": round(value),
             "detail_zh": f"上位机 {value:.0f} ms 未发送心跳，板端看门狗已切断输出"} if key == "hb_timeout" else {}
    return extra | {"cause": key, "cause_id": cause, "message_zh": msg, "cause_zh": msg,
            "value": round(float(value), 4), "t": round(t_ms / 1000.0, 3), "board_t_ms": int(t_ms)}


def hb_status_dict(w: int | None) -> dict:
    """心跳 status 字 → status() 里的 reset / hb_flags（旧固件没有这个字：都为 None）。"""
    if w is None:
        return {"reset": None, "hb_flags": None, "boot": None}
    return {"reset": RESET_NAMES.get(w & 0xFF, f"#{w & 0xFF}"), "hb_flags": [n for b, n in HB_FLAGS.items() if w & b],
            "boot": {"params": PARAM_SRC[(w >> 12) & 3], "selftest_ok": not (w & (1 << 11))}}


# dzctl 0.8.0 心跳 bit12-13：上电参数从哪来（旧固件为 0 = 显示成 flash；看 boot 字段前先确认固件版本）
PARAM_SRC = ("flash", "default_unsaved", "default_corrupt", "no_nvm")


def hb_status_event(w: int) -> tuple[str, str] | None:
    """status 字变化时要不要进时间线：异常复位（看门狗/锁死）、进安全态、堵转 → watchdog 类（严重，进告警条）。"""
    d = hb_status_dict(w)
    bad = (w & 0xFF) in (4, 6)
    if not bad and not (w & ((1 << 8) | (1 << 9))):
        return None
    why = f"板子复位原因：{d['reset']}" + (f"；{'、'.join(d['hb_flags'])}" if d["hb_flags"] else "")
    hint = "（主循环卡住被看门狗复位，板子已进安全态，确认原因后发 R 解除）" if bad else ""
    return ("watchdog", why + hint, "firmware:watchdog_reset" if bad else "firmware:safe_state")


def fw_rev_str(rev: int | None) -> str:
    """dzctl_fw_rev → "c3b7dfd" / "c3b7dfd+改动" / "未知"。"""
    if not rev:
        return "未知"
    return f"{rev & 0x0FFFFFFF:07x}" + ("+改动" if rev & 0x80000000 else "")


def readback_text(vals: dict, schema_hash: int, fw_rev: int | None, board_uid: int | None) -> str:
    head = [f"# dzbench 参数回读 {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"# schema_hash = {schema_hash:08X}", f"# fw_rev = {fw_rev_str(fw_rev)}",
            f"# board_uid = {board_uid:08X}" if board_uid else "# board_uid = 未知"]
    return "\n".join(head + [f"{k} = {v:.9g}" for k, v in vals.items()]) + "\n"


def estop_source(src: str) -> str:
    """estop(src) 的按键/调用方文字 → 规范 source：agent / ui（急停按钮、Esc、空格、其他界面来源）。"""
    t = (src or "").strip().lower()
    if t.startswith("agent"):
        return "agent"
    return "ui"
