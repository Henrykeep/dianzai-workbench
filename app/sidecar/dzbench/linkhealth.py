"""链路心跳条：每秒一格 {好帧数 fps、CRC 坏帧、序号缺口丢帧、字节数}，带 dzlog 时间和曲线时间，点格子能跳回去。

通用机制：只看 dzframe 层（好/坏计数 + 板子发出的 seq），不认识任何具体对象/schema。
seq 是板子侧所有上行帧共用的 8 位计数（car_2wd 遥测+心跳共用一个 seq++），缺口 = 中间丢了的帧；
缺口 ≥128 当作板子复位/换了计数源，不计丢帧（宁可漏报，不误报）。
"""
from __future__ import annotations

import collections
import threading

KEEP_S = 600          # 留 10 分钟，够一局调参翻回去看


class LinkHealth:
    def __init__(self, keep_s: int = KEEP_S):
        self.lk = threading.Lock()
        self.cells: collections.deque = collections.deque(maxlen=keep_s)
        self.reset()

    def reset(self) -> None:
        with self.lk:
            self.cells.clear()
            self._last_seq: int | None = None
            self._drops = 0
            self._t_open: float | None = None
            self._base = (0, 0, 0)       # 本格开头的 good/bad/rx_bytes
            self._idx = 0

    def rebase(self) -> None:
        """解析器重建（重连 / 回放跳转）：计数归零、seq 重新起算，已收的格子保留。"""
        with self.lk:
            self._last_seq, self._drops, self._t_open = None, 0, None

    def on_frame(self, seq: int) -> None:
        with self.lk:
            if self._last_seq is not None:
                gap = (seq - self._last_seq - 1) & 0xFF
                if 0 < gap < 128:
                    self._drops += gap
            self._last_seq = seq

    def tick(self, now: float, good: int, bad: int, rx: int,
             log_t: float | None, plot_t: float | None) -> list[dict]:
        """每次 status() 调；满 1 s 收一格。返回新收的格子（通常 0 或 1 个）。"""
        out = []
        with self.lk:
            if self._t_open is None:
                self._t_open, self._base = now, (good, bad, rx)
                return out
            dt = now - self._t_open
            if dt < 1.0:
                return out
            g, b, r = good - self._base[0], bad - self._base[1], rx - self._base[2]
            c = {"i": self._idx, "dt": round(dt, 3), "fps": round(max(g, 0) / dt, 1),
                 "crc": max(b, 0), "drops": self._drops, "bytes": max(r, 0),
                 "log_t": None if log_t is None else round(log_t, 2),
                 "plot_t": None if plot_t is None else round(plot_t, 3)}
            self.cells.append(c)
            out.append(c)
            self._idx += 1
            self._drops = 0
            self._t_open, self._base = now, (good, bad, rx)
        return out

    def history(self) -> list[dict]:
        with self.lk:
            return list(self.cells)
