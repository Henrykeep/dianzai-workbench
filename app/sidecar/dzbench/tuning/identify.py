"""阶跃辨识与稳态判定（净室实现，只依据公开文献，见 docs/参考来源.md“净室重写算法来源”）。

- open_loop_pid：开环阶跃 → FOPDT（K、τ、L）。两点法：Smith (1972) 28.3 % / 63.2 % 时刻，
  τ = 1.5 (t63 − t28)，L = t63 − τ；再用 SIMC 规则（Skogestad 2003）出 PI：Kc = τ / (K (τc + L))，
  τI = min(τ, 4 (τc + L))；τc 取保守值 max(L, τ/2, 50 ms)（Skogestad 建议 τc ≥ L，取大 = 更稳）。D = 0。
- steady_state：阶跃后末尾窗口的鲁棒判定（中位数绝对偏差估噪声、首尾分段均值估漂移、均值穿越估振荡）。
"""
from __future__ import annotations

import statistics


class IdentError(ValueError):
    """辨识失败（带中文原因）。"""


REASONS = {"steady": "已稳态", "too_few_samples": "样本太少", "warming_up": "刚开始/刚阶跃，还在暖机",
           "still_drifting": "还在漂移（窗口首尾差超过噪声）", "too_little_motion": "几乎没动：激励太小或执行器没响应",
           "oscillating": "在稳态附近持续振荡"}


def samples(t: list[float], y: list[float], u: list[float] | None = None) -> list[dict]:
    """秒 → 样本 dict（毫秒），给需要逐点结构的调用方。"""
    u = u or [0.0] * len(y)
    return [{"t": a * 1000.0, "actual": float(b), "input": float(c)} for a, b, c in zip(t, y, u)]


def _ss(ok, reason, noise=0.0, drift=0.0, amp=0.0):
    return {"steady": ok, "reason": reason, "text": REASONS[reason], "noise": round(noise, 6),
            "drift": round(drift, 6), "amplitude": round(amp, 6)}


def _med3(y):
    return [statistics.median(y[max(0, i - 1):i + 2]) for i in range(len(y))]


def _oscillating(y: list[float], thr: float) -> bool:
    f = _med3(y)
    mean = sum(f) / len(f)
    cross, side = 0, 0
    for v in f:                                  # 带滞回的均值穿越
        sd = 1 if v > mean + thr else -1 if v < mean - thr else 0
        if sd and side and sd != side:
            cross += 1
        if sd:
            side = sd
    return cross >= 3


def steady_state(t: list[float], y: list[float], t_step: float | None = None, window_s: float = 0.3,
                 warmup_s: float = 0.2, span_ref: float | None = None, base_s: float | None = None) -> dict:
    """阶跃后是否已稳。t_step = 阶跃时刻（秒）；不给时把前 3 个样本当基线。span_ref = 期望变化幅度；不给时用 y 极差。
    返回 {steady, reason, text, noise, drift, amplitude}。"""
    if len(t) < 8:
        return _ss(False, "too_few_samples")
    if t_step is None:
        t_step = t[min(2, len(t) - 1)]
    # base_s：基线只取阶跃前这么长（多段实验必须给：四段 SP→SP−Δ→SP→SP+Δ→SP 的全部历史中位数正好≈最终 SP，
    # 幅度被算成 0 → 误判 too_little_motion；哪边取中位数取决于采样个数/时序，Windows 上更容易翻）
    pre = [v for a, v in zip(t, y) if a < t_step and (base_s is None or a >= t_step - base_s)] or \
        [v for a, v in zip(t, y) if a < t_step] or y[:3]
    y0 = statistics.median(pre)
    if t[-1] - t_step < warmup_s + window_s:
        return _ss(False, "warming_up")
    win = [v for a, v in zip(t, y) if a >= t[-1] - window_s]
    if len(win) < 6:
        return _ss(False, "too_few_samples")
    span = abs(span_ref) if span_ref is not None else (max(y) - min(y))
    amp = abs(statistics.median(win) - y0)
    if span < 1e-9 or amp < 0.1 * span:
        return _ss(False, "too_little_motion", amp=amp)
    f = _med3(win)
    noise = 1.4826 * statistics.median(abs(a - b) for a, b in zip(win, f))      # MAD → σ（高斯一致常数）
    q = max(2, len(win) // 4)
    drift = abs(sum(win[-q:]) / q - sum(win[:q]) / q)
    if _oscillating(win, max(3 * noise, 0.01 * span)):
        return _ss(False, "oscillating", noise, drift, amp)
    ok = drift <= max(4 * noise, 0.02 * span)
    return _ss(ok, "steady" if ok else "still_drifting", noise, drift, amp)


def _cross_time(t, y, level):
    for i in range(1, len(y)):
        if y[i] >= level:
            a, b = y[i - 1], y[i]
            return t[i - 1] + (t[i] - t[i - 1]) * ((level - a) / (b - a) if b != a else 0.0)
    return None


def open_loop_pid(t: list[float], y: list[float], t_step: float, du: float, u: list[float] | None = None,
                  base_s: float = 0.35, tail_s: float = 0.7, min_change: float = 0.0) -> dict:
    """开环阶跃（控制量突增 du）→ FOPDT → SIMC PI 初值。返回 {pid:{p,i,d}, K, tau_s, dead_s, y0, y1, method}；
    数据不够或没动抛 IdentError（中文原因）。y 反向时先翻转再算，K 带回符号。"""
    if abs(du) < 1e-12:
        raise IdentError("控制量没有跳变（du = 0）")
    pre = [v for a, v in zip(t, y) if t_step - base_s <= a < t_step] or [v for a, v in zip(t, y) if a < t_step]
    post = [v for a, v in zip(t, y) if a >= t[-1] - tail_s and a > t_step]
    if len(pre) < 3 or len(post) < 3:
        raise IdentError("阶跃前或稳态段样本太少：阶跃前录 ≥0.35 s，阶跃后等到稳定再停")
    y0, y1 = statistics.median(pre), statistics.median(post)
    noise = statistics.pstdev(pre) if len(pre) > 1 else 0.0
    dy = y1 - y0
    if abs(dy) <= max(3 * noise, min_change, 1e-9):
        raise IdentError("输出几乎没动：加大台阶或检查执行器/反馈通道")
    sgn = 1.0 if dy > 0 else -1.0
    tt = [a for a in t if a >= t_step]
    yy = [sgn * (v - y0) / abs(dy) for a, v in zip(t, y) if a >= t_step]      # 归一化到 0 → 1
    t28, t63 = _cross_time(tt, yy, 0.283), _cross_time(tt, yy, 0.632)
    if t28 is None or t63 is None or t63 <= t28:
        raise IdentError("没找到 28.3 % / 63.2 % 两个时刻：响应太快（采样太稀）或没走完")
    tau = 1.5 * (t63 - t28)
    L = max(0.0, (t63 - t_step) - tau)
    K = dy / du
    tc = max(L, tau / 2, 0.05)
    kc = tau / (abs(K) * (tc + L))
    ti = min(tau, 4 * (tc + L))
    return {"pid": {"p": round(kc, 6), "i": round(kc / ti, 6), "d": 0.0}, "K": K, "tau_s": tau, "dead_s": L,
            "y0": y0, "y1": y1, "method": "smith-two-point+simc"}
