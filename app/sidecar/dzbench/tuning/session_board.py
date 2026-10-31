"""把真实会话（实机 / host-sim 板子）包成 autotune 的 board 接口：用户跑的和 tunegate 测的是同一份 autotune 代码（#108）。

read_params() / write_param(name, v)（走 session.set_param，受握手 max_delta）/ step(amp, n) → (t, r, y, u)（板上 step_start 阶跃）。
"""
from __future__ import annotations

import time

import numpy as np

from ..session import LinkError

ROLE_HINT = {"kp": "kp", "ki": "ki", "kd": "kd", "ff": "ff", "ulim": "ulim"}


def roles(schema, guess) -> dict:
    """{role: 参数名}：握手参数表写了 role 的优先；u_max 字段指向的参数 = ulim；其余按名字猜（猜不到就不调那一项）。"""
    names = [p["name"] for p in schema.params]
    out = {p["role"]: p["name"] for p in schema.params if p.get("role") in ROLE_HINT}
    st = (schema.step or [{}])[0]
    if isinstance(st.get("u_max"), str) and st["u_max"] in names:
        out.setdefault("ulim", st["u_max"])
    for r in ("kp", "ki", "kd"):
        if r not in out and (n := guess(names, r)) and n not in out.values():
            out[r] = n
    return out


class SessionBoard:
    def __init__(self, s, ch: int = 0, dt: float = 0.01):
        self.s, self.ch, self.dt, self.it = s, int(ch), float(dt), 1000

    def read_params(self) -> dict:
        return dict(self.s.params)

    def write_param(self, name: str, v: float) -> None:
        self.s.set_param(name, float(v))

    def step(self, amp: float, n: int):
        st = self.s.schema.step[self.ch]
        dur_ms = int(min(max(n * self.dt * 1000, 200), 30000))
        self.it += 1
        self.s.step_start(self.ch, self.it, float(amp), dur_ms)
        t_end = time.monotonic() + dur_ms / 1000 + 3.0
        while time.monotonic() < t_end:
            if getattr(self.s, "tx_locked", False):
                self.s.step_stop()
                raise LinkError("estop", "阶跃期间急停，整定中止", "确认安全后点“解除急停”再重来", "estop_clear")
            if self.s.step_wait(self.it, 0.1) is not None:
                break
        w = self.s.window(dur_ms / 1000)
        f = lambda k: np.array([float(v.get(k) or 0.0) for _, v in w])   # noqa: E731
        return np.array([a for a, _ in w]) - (w[0][0] if w else 0.0), f(st.get("sp_name") or "sp"), f(st["y"]), f(st.get("u") or "u")
