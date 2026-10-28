"""回放：把 .dzlog 里收到的字节按原时间节奏（可倍速）重新喂给会话，UI 看到的与现场一致。"""
from __future__ import annotations

import threading
import time

from .logfile import RX, read_log
from .transport import Transport


class ReplayTransport(Transport):
    def __init__(self, path, speed: float = 1.0):
        self.header, recs = read_log(path)
        self.recs = [(t, b) for t, d, b in recs if d == RX]
        self.name = f"replay:{path}"
        self.speed = max(speed, 0.01)
        self.i = 0
        self.t0 = None
        self.done = False
        self.paused = False
        self.base_pos = 0.0
        self.duration = self.recs[-1][0] if self.recs else 0.0
        self.lk = threading.Lock()

    # 时间轴：pos 是“记录里的秒”。实时对应关系 pos = base_pos + (now - base_wall) * speed
    def _now_pos(self) -> float:
        if self.t0 is None:
            return self.base_pos
        return self.base_pos + (0.0 if self.paused else (time.monotonic() - self.t0) * self.speed)

    def read(self) -> bytes:
        with self.lk:
            if self.t0 is None:
                self.t0 = time.monotonic()
            if self.i >= len(self.recs):
                self.done = True
                wait = 0.05
            else:
                t, b = self.recs[self.i]
                wait = t - self._now_pos()
                if wait <= 0 and not self.paused:
                    self.i += 1
                    return b
        time.sleep(min(max(wait / self.speed, 0.005), 0.05) if not self.paused else 0.05)
        return b""

    def seek(self, pos: float) -> None:
        """跳到记录里的第 pos 秒（之前的数据不重放）。"""
        with self.lk:
            pos = min(max(pos, 0.0), self.duration)
            self.i = next((k for k, (t, _) in enumerate(self.recs) if t >= pos), len(self.recs))
            self.base_pos, self.t0, self.done = pos, time.monotonic(), False

    def set_speed(self, speed: float) -> None:
        with self.lk:
            self.base_pos, self.t0 = self._now_pos(), time.monotonic()
            self.speed = min(max(speed, 0.05), 20.0)

    def pause(self, on: bool) -> None:
        with self.lk:
            self.base_pos, self.t0 = self._now_pos(), time.monotonic()
            self.paused = on

    def position(self) -> float:
        with self.lk:
            return min(self._now_pos(), self.duration)

    def write(self, data: bytes) -> None:   # 回放不下发任何东西（急停也只提示）
        pass

    def progress(self) -> float:
        return self.position() / self.duration if self.duration else 1.0
