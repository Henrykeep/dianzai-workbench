"""继电器自整定（Åström–Hägglund relay feedback）。只学算法（br3ttb PID AutoTune 的思路），代码自写。

做法：控制器换成继电器，误差 > +带 时输出 +d，< −带 时输出 −d（带 = noise_band 防抖）；对象会进入等幅振荡。
  Ku = 4d / (π·a)（a = 输出振荡半幅），Pu = 相邻同向峰的间隔
  相邻几个峰的幅度和周期都差不到 tol 才算收敛；超过 max_peaks 还不收敛就放弃。
只对稳定对象（电机速度环、温控）；钢珠、平衡车等开环不稳定对象必须在已闭合的外环下做 —— 调用方要先过 plant_stable 门禁。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .experiment import require_open_loop  # noqa: F401  —— 唯一入口门禁，接实验时先调它

# 现状（v0.9）：只有算法 + 仿真对象上的单测 [仿真]。真正跑实验需要固件提供“输出覆盖”通道（dzctl 把控制器输出换成上位机给的值），
# 还没做，所以这里不暴露成 Agent 工具；见 docs/25 P1。


@dataclass
class Relay:
    d: float                  # 继电器幅度（输出 = bias ± d）
    band: float = 0.0         # 噪声带
    bias: float = 0.0
    state: int = 1

    def __call__(self, sp: float, y: float) -> float:
        e = sp - y
        if e > self.band:
            self.state = 1
        elif e < -self.band:
            self.state = -1
        return self.bias + self.state * self.d


def analyze(t: list[float], y: list[float], d: float, sp: float | None = None, band: float = 0.0,
            tol: float = 0.05, need: int = 3, max_peaks: int = 20) -> dict:
    """从继电器实验的输出波形找峰，判收敛，算 Ku/Pu。返回 {ok, Ku, Pu, a, peaks, reason}。
    峰按“越过 sp±band 的半周期”取极值，不用逐点局部极值（那样噪声会造出假峰）。"""
    c = sum(y[len(y) // 2:]) / max(1, len(y) - len(y) // 2) if sp is None else sp
    hi, lo, side, best = [], [], 0, None
    for ti, yi in zip(t, y):
        s_ = 1 if yi > c + band else -1 if yi < c - band else side
        if s_ != side:
            if best is not None:
                (hi if side > 0 else lo).append(best)
            side, best = s_, (ti, yi)
        elif best is not None and ((side > 0 and yi > best[1]) or (side < 0 and yi < best[1])):
            best = (ti, yi)
    if len(hi) > max_peaks:
        hi, lo = hi[-max_peaks:], lo[-max_peaks:]
    if len(hi) < need + 1 or len(lo) < need:
        return {"ok": False, "reason": f"峰太少（{len(hi)} 个），延长实验或加大继电器幅度", "peaks": len(hi)}
    per = [b[0] - a[0] for a, b in zip(hi[-need - 1:], hi[-need:])]
    amp = [(h[1] - l[1]) / 2 for h, l in zip(hi[-need:], lo[-need:])]
    Pu, a = sum(per) / len(per), sum(amp) / len(amp)
    if a <= 0 or Pu <= 0:
        return {"ok": False, "reason": "振幅或周期为 0", "peaks": len(hi)}
    spread = max((max(per) - min(per)) / Pu, (max(amp) - min(amp)) / a)
    if spread > tol:
        return {"ok": False, "reason": f"最近 {need} 个峰还没稳定（差 {spread * 100:.0f}% > {tol * 100:.0f}%）", "peaks": len(hi),
                "Pu": Pu, "a": a}
    return {"ok": True, "Ku": 4 * d / (math.pi * a), "Pu": Pu, "a": a, "peaks": len(hi), "spread": spread}


def gains(Ku: float, Pu: float, rule: str = "tl") -> dict:
    """ZN 偏激进（超调大）；Tyreus–Luyben 更保守，默认用 TL。返回并联形式 kp/ki/kd（ki = kp/Ti，kd = kp·Td）。"""
    if rule == "zn":
        kp, Ti, Td = 0.6 * Ku, Pu / 2, Pu / 8
    elif rule == "zn_pi":
        kp, Ti, Td = 0.45 * Ku, Pu / 1.2, 0.0
    else:
        kp, Ti, Td = Ku / 2.2, 2.2 * Pu, Pu / 6.3
    return {"kp": kp, "ki": kp / Ti, "kd": kp * Td, "rule": rule}


def simulate_fopdt(K: float, tau: float, L: float, d: float, sp: float = 1.0, band: float = 0.0, T: float = 20.0,
                   dt: float = 0.001, noise: float = 0.0, seed: int = 0) -> tuple[list[float], list[float]]:
    """一阶惯性 + 纯滞后对象在继电器下的响应（单测和仿真演示用）。"""
    import random
    rnd = random.Random(seed)
    r = Relay(d, band, bias=sp / K)
    n_delay = max(1, int(L / dt))
    buf = [sp / K] * n_delay
    y, ts, ys = 0.0, [], []
    for k in range(int(T / dt)):
        ym = y + (rnd.gauss(0, noise) if noise else 0.0)
        buf.append(r(sp, ym))
        u = buf.pop(0)
        y += dt * (K * u - y) / tau
        ts.append(k * dt)
        ys.append(ym)
    return ts, ys
