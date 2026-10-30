"""一次连接的全部状态：收帧 → 解码 → 缓存；参数读写（等 ACK、重发）；急停；原始日志。

线程模型：传输层后台线程调用 _on_bytes；对外 API 线程安全；事件通过 emit 回调送出（server 负责转到 asyncio）。
"""
from __future__ import annotations

import collections
import pathlib
import re
import struct
import threading
import time
from typing import Callable

from . import lastsession, snapshots
from ._dzlink import DATA, HEARTBEAT, PARAM_ACK, PARAM_SET, Parser, encode
from .textparse import KvParser
from .framedef import FrameDefError, FrameDefParser
from .events import Timeline, crc_spike
from .linkhealth import LinkHealth
from .linkstate import LinkState
from .logfile import RX, TX, LogWriter
from . import ports as _ports
from .ports import PortOpenError, explain_open_error, identity, probe_baud
from .replay import ReplayTransport
from .schema import Schema, find_by_hash
from .transport import SIM_PREFIX, Transport, open_transport

ID_CMD, ID_ESTOP = 0x7E, 0x7F
ACK_STATUS = {0: "ok", 1: "clamped", 2: "bad_id", 3: "bad_len", 4: "bad_value"}
HB_TIMEOUT_S = 2.0          # = linkstate.LOST_AFTER_S；板子心跳 500 ms，任一合法帧都算活着


class LinkError(Exception):
    """带“怎么修”的错误：UI 原样显示 message 和 fix。"""

    def __init__(self, code: str, message: str, fix: str = ""):
        super().__init__(message)
        self.code, self.message, self.fix = code, message, fix

    def as_dict(self) -> dict:
        return {"type": "error", "code": self.code, "message": self.message, "fix": self.fix}


class Session:
    def __init__(self, emit: Callable[[dict], None] = lambda e: None, log_dir: pathlib.Path | None = None,
                 history_s: float = 120.0):
        self.emit = emit
        self.log_dir = log_dir or snapshots.base_dir() / "logs"
        self.lock = threading.RLock()
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
        self.hb_status: int | None = None        # dzctl 0.5.0 心跳第 4 个 u32：低 8 位复位原因 + DZCTL_HB_* 标志
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
        self._raw: collections.deque = collections.deque()
        self._raw_bytes = 0
        self.raw_dropped = 0
        self.kv = KvParser()
        self._uid_marked = False
        self.tx_locked = False               # 急停后锁住侧车的一切主动发送（预设/定时/触发/原始），R 或重新连接才解

    # ------------------------------------------------------------------ 连接
    def connect(self, port: str, baud: int | None = None, log: bool = True) -> dict:
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
            tr = ReplayTransport(port[7:]) if port.startswith("replay:") else self._open(port, baud or 0)
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
            self.hb_status = None
            if isinstance(tr, ReplayTransport) and tr.header.get("schema_hash"):
                self._bind_schema(int(tr.header["schema_hash"], 16))
            if log and not isinstance(tr, ReplayTransport):
                self.start_log()
        with self.lock:
            self._gen += 1
            gen = self._gen
        tr.start(self._on_bytes, lambda msg: self._on_transport_error(msg, gen))
        if not isinstance(tr, ReplayTransport):
            threading.Thread(target=self._host_heartbeat, args=(gen,), daemon=True).start()
        return {"port": port, "baud": baud, "note": note}

    HOST_HB_PERIOD_S = 0.25   # 固件 dzctl_wd 超时 1000 ms：侧车崩溃/拔线 -> 板子输出归零并锁存急停

    def _host_heartbeat(self, gen: int) -> None:
        """认出工作台固件（收到带 schema 的心跳）后，每 250 ms 发一帧上位机心跳（HEARTBEAT, LEN=0）。
        非工作台设备（AT 模块、printf）从不绑定 schema，就不会收到这些字节。急停锁定期间照发（心跳不驱动执行器）。"""
        while True:
            time.sleep(self.HOST_HB_PERIOD_S)
            with self.lock:
                if gen != self._gen and not self.reconnecting:
                    return
                bound = self.schema_hash is not None and self.tr is not None
            self._stall_check(gen)
            if bound and self.host_hb:
                try:
                    self._send(HEARTBEAT, 0, b"")
                except Exception:  # noqa: BLE001  传输层错误交给读线程的重连逻辑
                    pass

    def _stall_check(self, gen: int) -> None:
        """USB 转串口卡死（CH340 / CP210x 偶发：口还在、驱动不报错、就是不来数据）：开了 stall_s 才查。"""
        with self.lock:
            if not (self.stall_s > 0 and self.tr is not None and not self.reconnecting and gen == self._gen
                    and getattr(self.tr, "ser", None) is not None and self.last_rx > self._t_tr):
                return
            idle = time.monotonic() - self.last_rx
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
        if stale:
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
        只恢复链路，不解除急停。用户在这期间点了连接/断开（_gen 变了）就让位。"""
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
                    self.emit({"type": "resumed", "port": port, "message": f"侧车重启后已自动连回 {port}（急停仍锁着，确认安全后按 R）"})
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
                               "message": f"侧车重启后在 {moved} 找回了原来那块板（之前是 {port}），已经连上"})
                    return {"resumed": True, **r}
                except LinkError:
                    with self.lock:
                        gen0 = self._gen
            if self._gen != gen0:
                return {"resumed": False, "reason": "user_action"}
            self.down_reason = "port_ambiguous" if why == "ambiguous" else "port_not_found"
            lastsession.restore(rec)
            self.emit(LinkError(self.down_reason, f"侧车重启后没能自动连回上次的板子（{port} 不在了，也没在别的口找到它）",
                                "检查 USB 线，插好后在端口列表里选一下再点“连接”").as_dict())
            return {"resumed": False, "reason": self.down_reason}
        finally:
            with self.lock:
                self.resuming = False

    # ------------------------------------------------------------------ 收
    def _on_bytes(self, data: bytes) -> None:
        now = time.monotonic()
        with self.lock:
            self.rx_bytes += len(data)
            self.last_rx = now
            if self.log:
                self.log.write(RX, data)
            if self.raw_on:
                self._push_raw(now, RX, data)
            frames = self.parser.feed(data)
            text_mode = self.schema_hash is None and (self.schema is None or self.schema.d.get("virtual"))
        if text_mode:
            self._on_text(data, now)
        if frames:
            self.last_frame = now
        for kind, id_, seq, payload in frames:
            self.health.on_frame(seq)
            if kind == HEARTBEAT:
                self.last_hb = now
                if len(payload) >= 4:
                    h = struct.unpack_from("<I", payload)[0]
                    if len(payload) >= 8:
                        self.board_uid = struct.unpack_from("<I", payload, 4)[0] or None
                    if not self._uid_marked:
                        self._uid_marked = True
                        lastsession.mark_board(self.port, self.board_uid, h)
                    if len(payload) >= 12:
                        self.fw_rev = struct.unpack_from("<I", payload, 8)[0] or None
                    if len(payload) >= 16:
                        w = struct.unpack_from("<I", payload, 12)[0]
                        if w != self.hb_status:
                            self.hb_status = w
                            m = hb_status_event(w)
                            if m:
                                self._pending_marks.append(m)
                    if h != self.schema_hash:
                        self._bind_schema(h)
            elif kind == DATA and id_ == ID_RELAY and len(payload) == 1:
                self.relay_ack = payload[0]
            elif kind == DATA and id_ == ID_BB and len(payload) == 16:
                t_ms, code, arg, a, b = struct.unpack("<IHHff", payload)
                with self.lock:
                    self.bb_recs.append(bb_record(t_ms, code, arg, a, b))
            elif kind == DATA and self.schema and id_ == self.schema.telem_id:
                v = self.schema.decode(payload)
                if v is not None:
                    t = v["t_ms"] / 1000.0 if "t_ms" in v else now - self.t_connect
                    with self.lock:
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
    def _send(self, kind: int, id_: int, payload: bytes = b"") -> bool:
        with self.lock:
            tr = self.tr
            self.seq = (self.seq + 1) & 0xFF
            frame = encode(kind, id_, self.seq, payload)
            if self.log:
                self.log.write(TX, frame)
            if self.raw_on and tr:
                self._push_raw(time.monotonic(), TX, frame)
        if not tr:
            return False
        tr.write(frame)
        return True

    def estop(self) -> dict:
        """急停：连发 3 帧（丢一帧也能停）。没连接时如实告知，不假装成功。"""
        ok = False
        for _ in range(3):
            try:
                ok = self._send(DATA, ID_ESTOP) or ok
            except Exception:  # noqa: BLE001
                pass
        self.estop_count += 1
        self.tx_locked = True
        self.emit({"type": "tx_locked", "on": True})
        if isinstance(self.tr, ReplayTransport):
            return {"type": "estop", "sent": False, "message": "回放中：急停没有发给任何板子"}
        return {"type": "estop", "sent": ok,
                "message": "急停已发送（3 帧）" if ok else "未连接：急停没有送达！直接断电/拔电池"}

    def send_data(self, id_: int, payload: bytes) -> bool:
        """发任意 DATA 帧（应用自定义命令，如 car_2wd 的 id=1 轮速设定）。0x7E/0x7F 走专用接口。"""
        self._check_tx()
        if id_ in (ID_CMD, ID_ESTOP) or not 0 <= id_ <= 0xFF or len(payload) > 64:
            raise LinkError("bad_frame", f"DATA id={id_} 长度={len(payload)} 不允许", "急停/命令请用专用按钮；payload ≤ 64 字节")
        return self._send(DATA, id_, payload)

    def blackbox(self, wait_s: float = 0.6) -> list[dict]:
        """请求板子导出黑匣子（dzctl 0.6.0 DATA 0x7D len=0），收 wait_s 秒。只读，急停锁存时也允许（事后查原因正需要）。"""
        with self.lock:
            self.bb_recs = []
        if not self._send(DATA, ID_BB):
            raise LinkError("not_connected", "没连板子", "")
        time.sleep(wait_s)
        with self.lock:
            return list(self.bb_recs)

    RELAY_STATUS = {0: "ok", 1: "参数非法或板上没有这个 PID 回路", 2: "板子急停中"}

    def relay(self, loop: int, amp: float, hyst: float, timeout_s: float, wait_s: float = 0.5) -> dict:
        """让板上第 loop 个 PID 的输出换成继电器 ±amp（滞环 hyst，timeout_s 后板子自己恢复），等板子回执。"""
        self._check_tx()
        self.relay_ack = None
        if not self._send(DATA, ID_RELAY, struct.pack("<Bfff", loop, amp, hyst, timeout_s)):
            raise LinkError("not_connected", "没连板子", "")
        t_end = time.monotonic() + wait_s
        while time.monotonic() < t_end and getattr(self, "relay_ack", None) is None:
            time.sleep(0.01)
        a = getattr(self, "relay_ack", None)
        return {"ok": a == 0, "status": a, "why": "板子没回执（固件早于 dzctl 0.7.0？）" if a is None else self.RELAY_STATUS.get(a, str(a))}

    def relay_stop(self) -> bool:
        return self._send(DATA, ID_RELAY)

    def cmd(self, c: str, n: int | None = None) -> bool:
        ok = self._send(DATA, ID_CMD, c.encode()[:1] + (bytes([n]) if n is not None else b""))
        if ok and c == "R" and self.tx_locked:        # 人按了“解除急停 R”：侧车发送一起解锁
            self.tx_locked = False
            self.emit({"type": "tx_locked", "on": False})
        return ok

    def _check_tx(self) -> None:
        if self.tx_locked:
            raise LinkError("tx_locked", "急停后侧车的预设/定时/触发/原始发送已全部停用", "确认安全后点“解除急停 R”")

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
        v, clamped_here = self.schema.clamp(name, float(value)) if self.schema and name in self.schema.param_index else (value, False)
        applied, status = self._param_rpc(name, struct.pack("<f", v))
        out = {"name": name, "requested": value, "applied": applied, "status": "clamped" if clamped_here else status}
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

    def mark(self, kind: str, text: str) -> dict:
        """往事件时间线记一条（带两种时间）并广播。"""
        with self.lock:
            log_t, plot_t = self._times_locked(time.monotonic())
        e = self.timeline.add(kind, text, log_t, plot_t)
        self.emit(e)
        return e

    def link_state(self, now: float | None = None) -> dict | None:
        """唯一的连接状态（见 linkstate.py）；变化或到保活间隔时返回一条 link.state，否则 None。"""
        now = time.monotonic() if now is None else now
        with self.lock:
            return self.link.update(now, port=self.port, port_open=self.tr is not None,
                                    reconnecting=self.reconnecting or (self.resuming and self.tr is None), t_connect=self._t_tr,
                                    last_frame=self.last_frame,
                                    reason="resuming" if self.resuming and self.tr is None else self.down_reason)

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
            if self.tr is not None:
                log_t, plot_t = self._times_locked(now)
                hist = self.health.history()
                st["hb"] = self.health.tick(now, self.parser.good, self.parser.bad, self.rx_bytes, log_t, plot_t)
                marks += [("crc", f"CRC 坏帧突增：1 秒 {c['crc']} 帧") for c in st["hb"] if crc_spike(c, hist)]
                if self._was_alive and not alive and not self.reconnecting:
                    marks.append(("watchdog", f"{HB_TIMEOUT_S} s 没收到板子心跳（板端看门狗应已急停）"))
            self._was_alive = alive
        for k, txt in marks:
            self.mark(k, txt)
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
HB_FLAGS = {1 << 8: "安全态", 1 << 9: "堵转", 1 << 10: "急停"}


def hb_status_dict(w: int | None) -> dict:
    """心跳 status 字 → status() 里的 reset / hb_flags（旧固件没有这个字：都为 None）。"""
    if w is None:
        return {"reset": None, "hb_flags": None}
    return {"reset": RESET_NAMES.get(w & 0xFF, f"#{w & 0xFF}"), "hb_flags": [n for b, n in HB_FLAGS.items() if w & b]}


def hb_status_event(w: int) -> tuple[str, str] | None:
    """status 字变化时要不要进时间线：异常复位（看门狗/锁死）、进安全态、堵转 → watchdog 类（严重，进告警条）。"""
    d = hb_status_dict(w)
    bad = (w & 0xFF) in (4, 6)
    if not bad and not (w & ((1 << 8) | (1 << 9))):
        return None
    why = f"板子复位原因：{d['reset']}" + (f"；{'、'.join(d['hb_flags'])}" if d["hb_flags"] else "")
    hint = "（主循环卡住被看门狗复位，板子已进安全态，确认原因后发 R 解除）" if bad else ""
    return ("watchdog", why + hint)


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
