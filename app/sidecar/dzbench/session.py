"""一次连接的全部状态：收帧 → 解码 → 缓存；参数读写（等 ACK、重发）；急停；原始日志。

线程模型：传输层后台线程调用 _on_bytes；对外 API 线程安全；事件通过 emit 回调送出（server 负责转到 asyncio）。
"""
from __future__ import annotations

import collections
import pathlib
import struct
import threading
import time
from typing import Callable

from . import lastsession, snapshots
from ._dzlink import DATA, HEARTBEAT, PARAM_ACK, PARAM_SET, Parser, encode
from .textparse import KvParser
from .logfile import RX, TX, LogWriter
from . import ports as _ports
from .ports import PortOpenError, explain_open_error, identity, probe_baud
from .replay import ReplayTransport
from .schema import Schema, find_by_hash
from .transport import SIM_PREFIX, Transport, open_transport

ID_CMD, ID_ESTOP = 0x7E, 0x7F
ACK_STATUS = {0: "ok", 1: "clamped", 2: "bad_id", 3: "bad_len", 4: "bad_value"}
HB_TIMEOUT_S = 1.6


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
        self.on_sample: Callable[[dict], None] | None = None   # 触发发送用
        self.raw_on = False                  # 原始监视器（文本/HEX）开着才收集，省内存
        self._reset()

    def _reset(self) -> None:
        self.tr: Transport | None = None
        self.port = ""
        self.baud = 0
        self.parser = Parser()
        self.schema: Schema | None = None
        self.schema_hash: int | None = None
        self.board_uid: int | None = None        # 心跳里的芯片 ID（dzctl 0.3.0+；0/没有 = 未知）
        self.samples: collections.deque = collections.deque()
        self._new: list = []
        self.params: dict[str, float] = {}
        self._acks: dict[int, tuple[threading.Event, list]] = {}
        self.rx_bytes = 0
        self.last_hb = 0.0
        self.last_rx = 0.0
        self.log: LogWriter | None = None
        self.seq = 0
        self.estop_count = 0
        self.t_connect = 0.0
        self.reconnecting = False
        self.reconnects = 0
        self._raw: collections.deque = collections.deque()
        self._raw_bytes = 0
        self.raw_dropped = 0
        self.kv = KvParser()
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
                raise LinkError("open_failed", f"仿真板起不来：{e}", "在仓库根目录跑一次 make BOARD=host-sim APP=car_2wd 看报错") from e
            what, fix = explain_open_error(port, e)
            raise LinkError("open_failed", what, fix) from e
        self.ident = identity(port) if not port.startswith((SIM_PREFIX, "replay:")) else None
        lastsession.mark(port, baud or 0)
        with self.lock:
            self.tr, self.port, self.baud, self.t_connect = tr, port, baud or 0, time.monotonic()
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
            if bound and self.host_hb:
                try:
                    self._send(HEARTBEAT, 0, b"")
                except Exception:  # noqa: BLE001  传输层错误交给读线程的重连逻辑
                    pass

    def disconnect(self) -> None:
        lastsession.clear()                   # 用户主动断开 = 正常结束（侧车崩了不会走到这里）
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
        板子在断线期间应已按心跳超时自行进入安全状态（QUESTIONS 决定 1），这里不自动解除急停。"""
        k, warned = 0, False
        while True:
            time.sleep(self.RECONNECT_BACKOFF[min(k, len(self.RECONNECT_BACKOFF) - 1)])
            k += 1
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
                self.parser = Parser()
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
        for kind, id_, seq, payload in frames:
            if kind == HEARTBEAT:
                self.last_hb = now
                if len(payload) >= 4:
                    h = struct.unpack_from("<I", payload)[0]
                    if len(payload) >= 8:
                        self.board_uid = struct.unpack_from("<I", payload, 4)[0] or None
                    if h != self.schema_hash:
                        self._bind_schema(h)
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

    # ------------------------------------------------------------------ 快照 / 日志
    def snapshot_save(self, name: str, note: str = "") -> str:
        if not self.schema:
            raise LinkError("no_schema", "还没识别出参数表，不能存快照")
        return str(snapshots.save(self.schema.hash, name, dict(self.params), note))

    def snapshot_restore(self, name: str | None = None, defaults: bool = False) -> list[dict]:
        if not self.schema:
            raise LinkError("no_schema", "还没识别出参数表")
        vals = {p["name"]: p["default"] for p in self.schema.params} if defaults else snapshots.load(self.schema.hash, name)
        return [self.set_param(k, v, verify=True) for k, v in vals.items() if k in self.schema.param_index]

    def start_log(self) -> str:
        name = time.strftime("run_%Y%m%d_%H%M%S.dzlog")
        self.log = LogWriter(self.log_dir / name, {"port": self.port, "baud": self.baud,
                                                   "start": time.strftime("%Y-%m-%d %H:%M:%S"),
                                                   "schema_hash": f"{self.schema_hash:08X}" if self.schema_hash else None})
        return str(self.log.path)

    # ------------------------------------------------------------------ 状态
    def status(self) -> dict:
        now = time.monotonic()
        with self.lock:
            connected = self.tr is not None or self.reconnecting
            alive = connected and now - self.last_hb < HB_TIMEOUT_S
            st = {"type": "status", "connected": connected, "port": self.port, "baud": self.baud,
                  "alive": alive, "rx_bytes": self.rx_bytes, "good": self.parser.good, "bad": self.parser.bad,
                  "schema": f"{self.schema_hash:08X}" if self.schema_hash is not None else None,
                  "schema_ok": self.schema is not None, "log": str(self.log.path) if self.log else None,
                  "replay": isinstance(self.tr, ReplayTransport),
                  "reconnecting": self.reconnecting, "tx_locked": self.tx_locked, "reconnects": self.reconnects, "raw_dropped": self.raw_dropped,
                  "replay_progress": self.tr.progress() if isinstance(self.tr, ReplayTransport) else None}
            if isinstance(self.tr, ReplayTransport):
                st.update(replay_pos=round(self.tr.position(), 2), replay_len=round(self.tr.duration, 2),
                          replay_speed=self.tr.speed, replay_paused=self.tr.paused)
        if self.reconnecting:
            st["hint"] = "连接断开，正在自动重连…（线插回去即可；急停此时送不到板子，板子 1 秒没收到心跳会自己急停）"
        elif connected and self.parser.good >= 20 and self.parser.bad * 10 > self.parser.good:
            st["hint"] = (f"坏帧偏多（{self.parser.bad} 坏 / {self.parser.good} 好）：线上有干扰或乱码。"
                          "检查共地、杜邦线长度、电机线是否和串口线捆在一起；数据仍按校验通过的帧显示")
        elif connected and not alive and now - self.t_connect > HB_TIMEOUT_S:
            st["hint"] = ("收到字节但没有合法帧：波特率可能不对" if self.rx_bytes and not self.parser.good
                          else "超过 1.6 s 没有心跳：板子没上电/没跑工作台固件/线松了")
        return st
