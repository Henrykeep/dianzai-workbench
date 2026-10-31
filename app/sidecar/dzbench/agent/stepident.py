"""实测辨识阶跃时序（#80 / r10）：不认题号、不写死数值。

先做一次小幅探测阶跃，从录波里测出 噪声底 σ、增益 K、纯滞后 L、时间常数 T、最大响应速度 vmax，
再推出正式阶跃的 幅度 / 回起点容差 / 保持时间 / 回起点超时。唯一的外部约束是 app.yaml link.step 的物理上限（range）。
任何被控对象（位置、速度、温度、没见过的）都走同一套。
"""
from __future__ import annotations

import math
import statistics

PROBE_FRAC = 0.05      # 探测阶跃 = 物理量程的 5%（小幅，安全）
SETTLE_TC = 5.0        # 保持 = L + 5T（一阶对象 99%）
NOISE_K = 4.0          # 回起点容差 ≥ 4σ（噪声里不误判“没回位”）
MIN_SNR = 20.0         # 正式幅度 ≥ 20σ（看得清）
HOLD_MIN, HOLD_MAX = 0.5, 30.0
HOLD_BUDGET = 8.0      # 一轮阶跃的时间预算：速度受限的对象按实测速度缩小幅度，别让一轮拖太久
DUR_MIN_MS, DUR_MAX_MS = 200, 30000   # dzctl 0x7B 的帧约束


def identify(t: list[float], y: list[float], t_step: float, amp: float) -> dict | None:
    """从一段探测阶跃录波（t 秒、y 反馈、t_step 起跳时刻、amp 设定值变化量）测 σ/K/L/T/vmax。数据不够 → None。"""
    pre = [b for a, b in zip(t, y) if a < t_step]
    post = [(a - t_step, b) for a, b in zip(t, y) if a >= t_step]
    if len(pre) < 3 or len(post) < 5 or not amp:
        return None
    tp = [a for a in t if a < t_step]
    n = len(pre)                                  # 起跳前可能还在漂：去线性趋势后的残差 = 噪声底；起点 = 起跳前最后几拍
    mt, my = statistics.fmean(tp), statistics.fmean(pre)
    var_t = sum((a - mt) ** 2 for a in tp) or 1.0
    slope = sum((a - mt) * (b - my) for a, b in zip(tp, pre)) / var_t
    sigma = statistics.pstdev([b - (my + slope * (a - mt)) for a, b in zip(tp, pre)])
    y0 = statistics.fmean(pre[-max(3, n // 10):])
    tail = [b for a, b in post if a >= post[-1][0] * 0.8] or [post[-1][1]]
    dy = statistics.fmean(tail) - y0
    if abs(dy) <= max(3 * sigma, 1e-12):
        return {"sigma": sigma, "K": 0.0, "L": None, "T": None, "vmax": 0.0, "dy": dy, "ok": False,
                "why_zh": "探测阶跃没有可分辨的响应（被噪声淹没或执行器没动）"}
    s = math.copysign(1.0, dy)
    th = lambda f: next((a for a, b in post if s * (b - y0) >= f * abs(dy)), post[-1][0])  # noqa: E731
    t28, t63 = th(0.283), th(0.632)
    T = max(1.5 * (t63 - t28), 1e-3)          # 两点法（Smith）：一阶加纯滞后
    L = max(t63 - T, 0.0)
    t20, t80 = th(0.2), th(0.8)
    v = 0.6 * abs(dy) / (t80 - t20) if t80 > t20 else 0.0     # 20%→80% 平均速度（不对噪声求导）
    return {"sigma": sigma, "K": dy / amp, "L": L, "T": T, "vmax": v, "dy": dy, "y0": y0, "ok": True}


def derive(ident: dict | None, rng: float | None, probe_amp: float | None = None) -> dict:
    """辨识结果 + 物理量程 → 阶跃时序。辨识不出来就返回 {}（调用方用通用默认值，并如实标“未辨识”）。"""
    if not ident or not ident.get("ok"):
        return {}
    L, T, sigma = float(ident["L"]), float(ident["T"]), float(ident["sigma"])
    settle = L + SETTLE_TC * T
    amp = max((rng / 4.0) if rng else abs(ident["dy"]) * 4, MIN_SNR * sigma)
    if rng:
        amp = min(amp, float(rng))                                   # 只受物理上限约束
    if ident.get("vmax") and ident.get("K"):
        room = HOLD_BUDGET / 1.2 - settle
        cap = (abs(ident["dy"]) + ident["vmax"] * max(room, 0.0)) / abs(ident["K"])
        amp = max(min(amp, cap), MIN_SNR * sigma, abs(probe_amp or 0.0))
    extra = max(abs(amp * ident["K"]) - abs(ident["dy"]), 0.0) / ident["vmax"] if ident.get("vmax") else 0.0
    hold = min(max(1.2 * (settle + extra), HOLD_MIN), HOLD_MAX)     # 速度受限（饱和/限速）：多走的路按实测速度补时间
    tol = max(NOISE_K * sigma, 0.05 * amp)
    return {"step_target": round(amp, 4), "hold_s": round(hold, 3), "return_tol": round(tol, 4),
            "return_timeout_s": round(min(max(2 * settle + 1.0, 2.0), 60.0), 3),
            "step_dur_ms": int(min(max(hold * 1000, DUR_MIN_MS), DUR_MAX_MS)),
            "basis": {"sigma": round(sigma, 6), "K": round(ident["K"], 6), "L_s": round(L, 4), "T_s": round(T, 4),
                      "vmax": round(ident.get("vmax") or 0.0, 4), "range": rng, "source": "measured"}}
