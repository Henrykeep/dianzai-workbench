"""回放：把 .dzlog 里收到的字节按原时间节奏（可倍速）重新喂给会话，UI 看到的与现场一致。"""
from __future__ import annotations

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

    def read(self) -> bytes:
        if self.t0 is None:
            self.t0 = time.monotonic()
        if self.i >= len(self.recs):
            self.done = True
            time.sleep(0.05)
            return b""
        t, b = self.recs[self.i]
        wait = t / self.speed - (time.monotonic() - self.t0)
        if wait > 0:
            time.sleep(min(wait, 0.05))
            return b""
        self.i += 1
        return b

    def write(self, data: bytes) -> None:   # 回放不下发任何东西（急停也只提示）
        pass

    def progress(self) -> float:
        return self.i / len(self.recs) if self.recs else 1.0
