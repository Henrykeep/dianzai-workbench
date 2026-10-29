"""阶跃辨识与稳态判定——适配层，算法本体是 PID_Helper（GPL-3.0）的移植：
third_party/vendored/pid_helper/pid_helper_ident.py（见那里的 SOURCE.md）。

本文件只做三件事：秒 → 毫秒、按阶跃幅度换算绝对阈值（unit）、原因码换成本仓库的 snake_case + 中文。
另加一项原版没有的“振荡”判定（均值穿越 ≥3 次），因为闭环实验里持续振荡比漂移更常见。
删掉 vendored 目录时只需改这里。
"""
from __future__ import annotations

import pathlib
import statistics
import sys

_P = pathlib.Path(__file__).resolve().parents[4] / "third_party" / "vendored" / "pid_helper"   # 源码运行；打包版由
if _P.is_dir() and str(_P) not in sys.path:                                                    # PyInstaller --paths 收进去
    sys.path.insert(0, str(_P))

import pid_helper_ident as PH  # noqa: E402

IdentError = PH.IdentError

REASONS = {"steady": "已稳态", "too_few_samples": "样本太少", "warming_up": "刚开始/刚阶跃，还在暖机",
           "still_drifting": "还在漂移（窗口首尾差超过噪声）", "too_little_motion": "几乎没动：激励太小或执行器没响应",
           "oscillating": "在稳态附近持续振荡"}
_MAP = {"steady": "steady", "not-enough-baseline": "too_few_samples", "not-enough-post-step": "too_few_samples",
        "not-enough-recent-samples": "too_few_samples", "warming-up": "warming_up",
        "too-little-motion": "too_little_motion", "still-drifting": "still_drifting"}


def samples(t: list[float], y: list[float], u: list[float] | None = None) -> list[dict]:
    """秒 → PID_Helper 的样本 dict（毫秒）。"""
    u = u or [0.0] * len(y)
    return [{"t": a * 1000.0, "actual": float(b), "input": float(c)} for a, b, c in zip(t, y, u)]


def _ss(ok, reason, noise=0.0, drift=0.0, amp=0.0):
    return {"steady": ok, "reason": reason, "text": REASONS[reason], "noise": round(noise, 6),
            "drift": round(drift, 6), "amplitude": round(amp, 6)}


def _oscillating(y: list[float], thr: float) -> bool:
    f = [statistics.median(y[max(0, i - 1):i + 2]) for i in range(len(y))]
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
                 warmup_s: float = 0.2, span_ref: float | None = None) -> dict:
    """阶跃后是否已稳。t_step = 阶跃时刻（秒，同 t 的时间轴）；不给时把前 3 个样本当基线。
    span_ref = 期望的变化幅度（设定值阶跃量）；不给时用窗口内 y 的极差。
    返回 {steady, reason, text, noise, drift, amplitude}；warming_up / still_drifting → 应 OBSERVE 而不是改参数。"""
    if len(t) < 10 or t[-1] - t[0] < window_s:
        return _ss(False, "too_few_samples")
    if t_step is None:
        t_step = t[2]
    span = abs(span_ref) if span_ref is not None else (max(y) - min(y))
    if span < 1e-9:
        return _ss(False, "too_little_motion")
    unit = span / 2.0                            # 原版 0.2 最小幅度 ↔ 这里 10% 阶跃量
    r = PH.detect_step_steady(samples(t, y), t_step * 1000.0, base_ms=max(350.0, (t_step - t[0]) * 1000.0),
                              window_ms=window_s * 1000.0, min_observe_ms=(warmup_s + window_s) * 1000.0, unit=unit)
    reason = _MAP[r["reason"]]
    noise, drift = r.get("noise", 0.0), r.get("drift", 0.0)
    if reason in ("steady", "still_drifting"):
        win = [v for a, v in zip(t, y) if a >= t[-1] - window_s]
        f = [statistics.median(win[max(0, i - 1):i + 2]) for i in range(len(win))]
        hf = 1.4826 * statistics.median(abs(a - b) for a, b in zip(win, f))   # 只含高频抖动，不被慢振荡撑大
        if _oscillating(win, max(3 * hf, 0.01 * span)):
            reason = "oscillating"
    return _ss(reason == "steady", reason, noise, drift, r.get("amplitude", 0.0))


def open_loop_pid(t: list[float], y: list[float], t_step: float, du: float, u: list[float] | None = None,
                  base_s: float = 0.35, tail_s: float = 0.7, min_change: float = 0.0) -> dict:
    """开环阶跃（控制量突增 du）→ FOPDT（K、τ、L，两点法 10%/63.2%）→ 保守 λ 整定的 PID 初值。
    返回 {pid:{p,i,d}, K, tau_s, dead_s, y0, y1}；数据不够或没动抛 IdentError（带中文原因）。
    y 下降（反向）时先翻转再算，K 带回符号。"""
    sgn = 1.0
    pre = [v for a, v in zip(t, y) if a < t_step]
    post = [v for a, v in zip(t, y) if a >= t[-1] - tail_s]
    if pre and post and sum(post) / len(post) < sum(pre) / len(pre):
        sgn = -1.0
    yy = [sgn * v for v in y]
    noise = statistics.pstdev(pre) if len(pre) > 1 else 0.0   # 变化须超过基线噪声 3 倍和 min_change（你的量纲）
    r = PH.estimate_pid_from_step(samples(t, yy, u), t_step * 1000.0, abs(du), base_ms=base_s * 1000.0,
                                  tail_ms=tail_s * 1000.0, min_delta=max(3 * noise, min_change, 1e-9))
    return {"pid": r["pid"], "K": sgn * r["K"] * (1 if du > 0 else -1), "tau_s": r["tau_ms"] / 1000.0,
            "dead_s": r["dead_ms"] / 1000.0, "y0": sgn * r["y0"], "y1": sgn * r["y1"], "method": r["method"]}


# 分阶段搜索的候选与打分原样转出（PID_Helper：纯 P → 加 I → 加 D）
pure_p_candidates = PH.pure_p_candidates
speed_i_candidates = PH.speed_i_candidates
speed_d_candidates = PH.speed_d_candidates
evaluate_pure_p = PH.evaluate_pure_p
evaluate_speed_stage = PH.evaluate_speed_stage
score_speed_i = PH.score_speed_i
score_speed_d = PH.score_speed_d
