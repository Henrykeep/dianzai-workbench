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

from . import snapshots
from ._dzlink import DATA, HEARTBEAT, PARAM_ACK, PARAM_SET, Parser, encode
from .logfile import RX, TX, LogWriter
from .ports import probe_baud
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
        self._reset()

    def _reset(self) -> None:
        self.tr: Transport | None = None
        self.port = ""
        self.baud = 0
        self.parser = Parser()
        self.schema: Schema | None = None
        self.schema_hash: int | None = None
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

    # ------------------------------------------------------------------ 连接
    def connect(self, port: str, baud: int | None = None, log: bool = True) -> dict:
        self.disconnect()
        note = ""
        if not port.startswith((SIM_PREFIX, "replay:")) and not baud:
            baud, note = probe_baud(port)
            if not baud:
                if note.startswith("打不开"):
                    raise LinkError("open_failed", note)
                raise LinkError("no_frames", note, "也可以在波特率下拉框手动选一个再连")
        try:
            tr = ReplayTransport(port[7:]) if port.startswith("replay:") else open_transport(port, baud or 0)
        except Exception as e:  # noqa: BLE001
            raise LinkError("open_failed", f"打不开 {port}：{e}",
                            "确认没有别的程序（串口助手、Keil/CCS 调试）占着这个口，拔插 USB 再试") from e
        with self.lock:
            self.tr, self.port, self.baud, self.t_connect = tr, port, baud or 0, time.monotonic()
            if isinstance(tr, ReplayTransport) and tr.header.get("schema_hash"):
                self._bind_schema(int(tr.header["schema_hash"], 16))
            if log and not isinstance(tr, ReplayTransport):
                self.start_log()
        tr.start(self._on_bytes, self._on_transport_error)
        return {"port": port, "baud": baud, "note": note}

    def disconnect(self) -> None:
        with self.lock:
            tr, log = self.tr, self.log
            self.tr = None
        if tr:
            tr.close()
        if log:
            log.close()
        with self.lock:
            self._reset()

    def _on_transport_error(self, msg: str) -> None:
        self.emit(LinkError("link_lost", f"连接断开：{msg}", "检查 USB 线/供电；板子复位后点“连接”重连").as_dict())

    # ------------------------------------------------------------------ 收
    def _on_bytes(self, data: bytes) -> None:
        now = time.monotonic()
        with self.lock:
            self.rx_bytes += len(data)
            self.last_rx = now
            if self.log:
                self.log.write(RX, data)
            frames = self.parser.feed(data)
        for kind, id_, seq, payload in frames:
            if kind == HEARTBEAT:
                self.last_hb = now
                if len(payload) >= 4:
                    h = struct.unpack_from("<I", payload)[0]
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

    def _bind_schema(self, h: int) -> None:
        self.schema_hash = h
        s = find_by_hash(h)
        with self.lock:
            self.schema = s
        if s:
            self.emit({"type": "schema", "schema": s.summary()})
            threading.Thread(target=self.read_all_params, daemon=True).start()
        else:
            self.emit(LinkError("schema_missing", f"板子的数据格式（哈希 {h:08X}）在本机找不到对应的 link_schema.json",
                                "在仓库根目录对这块板和应用跑一次 make（例如 make BOARD=xxx APP=car_2wd），"
                                "它会生成 build/.../linkgen/link_schema.json；或者固件比工程旧/新，重新烧录").as_dict())

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
        if isinstance(self.tr, ReplayTransport):
            return {"type": "estop", "sent": False, "message": "回放中：急停没有发给任何板子"}
        return {"type": "estop", "sent": ok,
                "message": "急停已发送（3 帧）" if ok else "未连接：急停没有送达！直接断电/拔电池"}

    def send_data(self, id_: int, payload: bytes) -> bool:
        """发任意 DATA 帧（应用自定义命令，如 car_2wd 的 id=1 轮速设定）。0x7E/0x7F 走专用接口。"""
        if id_ in (ID_CMD, ID_ESTOP) or not 0 <= id_ <= 0xFF or len(payload) > 64:
            raise LinkError("bad_frame", f"DATA id={id_} 长度={len(payload)} 不允许", "急停/命令请用专用按钮；payload ≤ 64 字节")
        return self._send(DATA, id_, payload)

    def cmd(self, c: str, n: int | None = None) -> bool:
        return self._send(DATA, ID_CMD, c.encode()[:1] + (bytes([n]) if n is not None else b""))

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

    def set_param(self, name: str, value: float) -> dict:
        v, clamped_here = self.schema.clamp(name, float(value)) if self.schema and name in self.schema.param_index else (value, False)
        applied, status = self._param_rpc(name, struct.pack("<f", v))
        return {"name": name, "requested": value, "applied": applied, "status": "clamped" if clamped_here else status}

    def read_param(self, name: str) -> float:
        return self._param_rpc(name, b"")[0]

    def read_all_params(self) -> dict:
        out = {}
        for p in (self.schema.params if self.schema else []):
            try:
                out[p["name"]] = self.read_param(p["name"])
            except LinkError:
                break
        return out

    # ------------------------------------------------------------------ 快照 / 日志
    def snapshot_save(self, name: str, note: str = "") -> str:
        if not self.schema:
            raise LinkError("no_schema", "还没识别出参数表，不能存快照")
        return str(snapshots.save(self.schema.hash, name, dict(self.params), note))

    def snapshot_restore(self, name: str | None = None, defaults: bool = False) -> list[dict]:
        if not self.schema:
            raise LinkError("no_schema", "还没识别出参数表")
        vals = {p["name"]: p["default"] for p in self.schema.params} if defaults else snapshots.load(self.schema.hash, name)
        return [self.set_param(k, v) for k, v in vals.items() if k in self.schema.param_index]

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
            connected = self.tr is not None
            alive = connected and now - self.last_hb < HB_TIMEOUT_S
            st = {"type": "status", "connected": connected, "port": self.port, "baud": self.baud,
                  "alive": alive, "rx_bytes": self.rx_bytes, "good": self.parser.good, "bad": self.parser.bad,
                  "schema": f"{self.schema_hash:08X}" if self.schema_hash is not None else None,
                  "schema_ok": self.schema is not None, "log": str(self.log.path) if self.log else None,
                  "replay": isinstance(self.tr, ReplayTransport),
                  "replay_progress": self.tr.progress() if isinstance(self.tr, ReplayTransport) else None}
        if connected and not alive and now - self.t_connect > HB_TIMEOUT_S:
            st["hint"] = ("收到字节但没有合法帧：波特率可能不对" if self.rx_bytes and not self.parser.good
                          else "超过 1.6 s 没有心跳：板子没上电/没跑工作台固件/线松了")
        return st
