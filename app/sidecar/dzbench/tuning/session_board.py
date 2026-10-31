"""把真实会话（实机 / host-sim 板子）包成 autotune 的 board 接口：用户跑的和 tunegate 测的是同一份 autotune 代码（#108）。

read_params() / write_param(name, v)（走 session.set_param，受握手 max_delta）/ step(amp, n) → (t, r, y, u)（板上 step_start 阶跃）。
"""
from __future__ import annotations

import time

import numpy as np

from ..session import LinkError

# 握手参数表的 role（app.yaml link.params.<名>.role，gen_link 原样带进握手；没写 = null）→ autotune 角色
ROLE_MAP = {"P": "kp", "I": "ki", "D": "kd", "FF": "ff"}       # LIM / other 不参与整定
ROLES = ("P", "I", "D", "FF", "LIM", "other")


def tunable(schema) -> list[dict]:
    return [p for p in schema.params if isinstance(p.get("min"), (int, float)) and isinstance(p.get("max"), (int, float))
            and p["max"] > p["min"] and str(p.get("type", "f32")) in ("f32", "f64", "float", "double")]


def declared(schema) -> tuple[dict, list[str]]:
    """({autotune 角色: 参数名}, 没声明 role 的可调参数名)。只认握手里的声明，不按名字猜。"""
    out, missing = {}, []
    for p in tunable(schema):
        r = p.get("role")
        if r is None:
            missing.append(p["name"])
        elif r in ROLE_MAP:
            out[ROLE_MAP[r]] = p["name"]
    return out, missing


def suggest(schema, guess) -> dict:
    """只当建议给人确认：link.step.u_max 指向的参数 → LIM，其余按名字猜 P/I/D，猜不到 = other。"""
    names = [p["name"] for p in tunable(schema)]
    st = (schema.step or [{}])[0]
    out = {n: "LIM" for n in names if n == st.get("u_max")}
    for r, k in (("P", "kp"), ("I", "ki"), ("D", "kd")):
        n = guess(names, k)
        if n and n not in out:
            out[n] = r
    return {n: out.get(n, "other") for n in names}


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
