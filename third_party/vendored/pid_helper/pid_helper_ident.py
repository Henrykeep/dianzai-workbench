"""PID_Helper 的阶跃辨识 / 稳态判定 / 分阶段打分，逐函数移植到 Python。

Source: gitee.com/qianmonai/PID_Helper@17813ca src/shared/pid-identification.ts
Source: gitee.com/qianmonai/PID_Helper@17813ca src/shared/float-utils.ts（normalize_float / clamp_float）
License: GPL-3.0-or-later（见同目录 LICENSE）。改动见 SOURCE.md。

样本是 dict：{"t": 接收时间 ms, "actual": 反馈, "input": 控制量, "ts": 板上时间戳 ms（可选）}。
"""
from __future__ import annotations

import math
import struct

CONSERVATIVE_LAMBDA_DEAD_TIME_FACTOR = 3.5
CONSERVATIVE_LAMBDA_TIME_CONSTANT_FACTOR = 0.95
CONSERVATIVE_LAMBDA_MIN_MS = 150
CONSERVATIVE_INTEGRAL_TIME_FACTOR = 4.8
CONSERVATIVE_INTEGRAL_TIME_MIN_SECONDS = 3
CONSERVATIVE_DERIVATIVE_TIME_FACTOR = 0.75
PURE_P_TARGET_STEADY_ERROR_PERCENT = 18
PURE_P_MIN_STEADY_ERROR_PERCENT = 15
PURE_P_MAX_STEADY_ERROR_PERCENT = 20


class IdentError(ValueError):
    pass


# ---------------------------------------------------------------- float-utils.ts
def normalize_float(v: float) -> float:
    if not math.isfinite(v):
        return v
    f = struct.unpack("f", struct.pack("f", v))[0]
    return 0.0 if f == 0 else float(f"{f:.7g}")


def clamp_float(v: float, lo: float = -math.inf, hi: float = math.inf) -> float:
    return normalize_float(min(hi, max(lo, v)))


# ---------------------------------------------------------------- 统计小工具
def _avg(v):
    return sum(v) / len(v)


def _clamp(v, lo, hi):
    return min(hi, max(lo, v))


def _median(v):
    s = sorted(v)
    return s[len(s) // 2] if s else 0.0


def _std(v):
    if len(v) < 2:
        return 0.0
    c = _avg(v)
    return math.sqrt(sum((x - c) ** 2 for x in v) / len(v))


def _trimmed_avg(v):
    if len(v) <= 4:
        return _avg(v)
    s = sorted(v)
    k = max(1, int(len(s) * 0.15))
    m = s[k:len(s) - k]
    return _avg(m or s)


def _range(v):
    return max(v) - min(v) if v else 0.0


# ---------------------------------------------------------------- 候选网格
def pure_p_candidates(seed_p: float = 0.2, min_p: float = 0.02, max_p: float = 500) -> list[float]:
    fixed = [0.02, 0.04, 0.06, 0.08, 0.12, 0.18, 0.27, 0.4, 0.6, 0.9, 1.3, 1.9, 2.8, 4.2, 6.3, 9.5,
             14, 21, 32, 48, 72, 108, 160, 240, 360]
    seed = [seed_p * r for r in (0.2, 0.35, 0.5, 0.7, 0.9, 1.1, 1.4, 1.8, 2.4, 3.2)] if seed_p > 0 else []
    lo = max(0.001, min_p)
    return sorted({normalize_float(v) for v in fixed + seed if math.isfinite(v) and lo <= v <= max_p})


def _uniq(values, lo=0.0, hi=500.0):
    return sorted({clamp_float(v, lo, hi) for v in values if math.isfinite(v)})


def speed_i_candidates(kp: float, max_i: float = 500) -> list[float]:
    return _uniq([kp * r for r in (0, 0.003, 0.005, 0.0075, 0.01, 0.013, 0.017, 0.022, 0.028, 0.035)], 0, max_i)


def speed_d_candidates(kp: float, max_d: float = 500) -> list[float]:
    return _uniq([kp * r for r in (0, 0.0002, 0.00035, 0.0005, 0.00075, 0.001, 0.00135, 0.0018, 0.0024)], 0, max_d)


# ---------------------------------------------------------------- 分阶段指标与打分
def _tail(samples, start, tail_ms, what):
    rel = sorted((s for s in samples if s["t"] >= start), key=lambda s: s["t"])
    if len(rel) < 6:
        raise IdentError(f"{what}采样点不足，请延长采样时间")
    last = rel[-1]["t"]
    tail = [s for s in rel if last - s["t"] <= tail_ms]
    if len(tail) < 4:
        raise IdentError(f"{what}末段采样不足，请延长采样时间")
    return rel, tail


def _common(rel, tail, target):
    mag = max(abs(target), 0.001)
    act = [s["actual"] for s in tail]
    inp = [s["input"] for s in tail]
    ss = _trimmed_avg(act)
    err = abs(target - ss)
    if target >= 0:
        over = max(0.0, max(s["actual"] for s in rel) - target)
    else:
        over = max(0.0, target - min(s["actual"] for s in rel))
    return mag, ss, err, err / mag * 100, over / mag * 100, _range(act), _range(act) / mag * 100, _range(inp)


def evaluate_pure_p(samples, target: float, start: float = 0, tail_ms: float = 900) -> dict:
    rel, tail = _tail(samples, start, tail_ms, "纯 P 辨识")
    mag, ss, err, errp, overp, rip, ripp, irip = _common(rel, tail, target)
    band = ((PURE_P_MIN_STEADY_ERROR_PERCENT - errp) * 2.5 if errp < PURE_P_MIN_STEADY_ERROR_PERCENT
            else (errp - PURE_P_MAX_STEADY_ERROR_PERCENT) * 1.5 if errp > PURE_P_MAX_STEADY_ERROR_PERCENT else 0)
    aggr = (10 - errp) * 3 if errp < 10 else 0
    score = abs(errp - PURE_P_TARGET_STEADY_ERROR_PERCENT) + band + aggr + overp * 1.8 + ripp * 0.35 + irip * 8
    n = normalize_float
    return {"steady_actual": n(ss), "steady_error": n(err), "steady_error_pct": n(errp), "overshoot_pct": n(overp),
            "ripple": n(rip), "ripple_pct": n(ripp), "input_ripple": n(irip), "score": round(score, 4)}


def evaluate_speed_stage(samples, target: float, start: float = 0, tail_ms: float = 900, hold_ms: float = 480) -> dict:
    rel, tail = _tail(samples, start, tail_ms, "速度环阶段辨识")
    mag, ss, err, errp, overp, rip, ripp, irip = _common(rel, tail, target)
    band = max(mag * 0.05, 0.25)
    settle = rel[-1]["t"] - start
    for s in rel:
        win = [c for c in rel if s["t"] <= c["t"] <= s["t"] + hold_ms]
        if len(win) >= 3 and all(abs(target - c["actual"]) <= band for c in win):
            settle = s["t"] - start
            break
    n = normalize_float
    return {"steady_actual": n(ss), "steady_error": n(err), "steady_error_pct": n(errp), "overshoot_pct": n(overp),
            "ripple": n(rip), "ripple_pct": n(ripp), "input_ripple": n(irip), "settling_ms": round(settle)}


def score_speed_i(m: dict, ref: dict | None = None) -> float:
    sc = m["steady_error_pct"] * 2.4 + m["overshoot_pct"] * 1.8 + m["ripple_pct"] * 0.45 + m["input_ripple"] * 10 \
        + m["settling_ms"] / 1000 * 0.4
    if ref:
        sc -= min(10, max(ref["steady_error_pct"] - m["steady_error_pct"], 0) * 0.9)
        sc += max(m["steady_error_pct"] - ref["steady_error_pct"], 0) * 1.5
        sc += max(m["overshoot_pct"] - (ref["overshoot_pct"] + 3), 0) * 2.3
        sc += max(m["ripple_pct"] - (ref["ripple_pct"] + 1.5), 0) * 0.9
        sc += max(m["input_ripple"] - (ref["input_ripple"] * 1.35 + 0.03), 0) * 28
    return round(sc, 4)


def score_speed_d(m: dict, ref: dict | None = None) -> float:
    sc = m["overshoot_pct"] * 2.4 + m["ripple_pct"] * 0.8 + m["input_ripple"] * 10 + m["steady_error_pct"] * 1.2 \
        + m["settling_ms"] / 1000 * 0.45
    if ref:
        sc -= min(10, max(ref["overshoot_pct"] - m["overshoot_pct"], 0) * 1.1)
        sc += max(m["overshoot_pct"] - ref["overshoot_pct"], 0) * 1.8
        sc += max(m["steady_error_pct"] - (ref["steady_error_pct"] + 1.5), 0) * 1.6
        sc += max(m["settling_ms"] - (ref["settling_ms"] + 250), 0) / 250 * 0.9
        sc += max(m["input_ripple"] - (ref["input_ripple"] * 1.25 + 0.02), 0) * 30
    return round(sc, 4)


# ---------------------------------------------------------------- 时间轴（优先用板上时间戳）
def _timeline(samples, step_at, base_ms):
    base = sorted((s for s in samples if s["t"] < step_at and step_at - s["t"] <= base_ms and "ts" in s
                   and math.isfinite(s["ts"])), key=lambda s: s["t"])
    if base:
        off = base[-1]["t"] - base[-1]["ts"]
        step_at, tm = step_at - off, (lambda s: s["ts"])
    else:
        tm = (lambda s: s["t"])
    rel = sorted((s for s in samples if tm(s) >= step_at - base_ms), key=tm)
    pre = [s for s in rel if tm(s) < step_at and step_at - tm(s) <= base_ms]
    post = [s for s in rel if tm(s) >= step_at]
    return step_at, tm, pre, post


def _interval(samples, tm):
    d = [tm(b) - tm(a) for a, b in zip(samples, samples[1:]) if tm(b) - tm(a) > 0]
    return _avg(d) if d else 0.0


def _median_denoise(samples, r=2):
    return [_median([c["actual"] for c in samples[max(0, i - r):i + r + 1]]) for i in range(len(samples))]


def _denoise(samples):
    med = _median_denoise(samples)
    if not med:
        return []
    ema, out = med[0], []
    for v in med:
        ema += (v - ema) * 0.42
        out.append(ema)
    return out


def detect_step_steady(samples, step_at: float, base_ms: float = 350, window_ms: float = 900,
                       min_settled: int = 6, min_observe_ms: float = 900, unit: float = 1.0) -> dict:
    """原 detectStepSteadyState。原版写死 900 ms 最短观察和绝对阈值 0.2/0.12/0.05/0.35（转速量纲）；
    这里做成参数：min_observe_ms，unit 乘到所有绝对阈值上（默认 1 = 与原版一致）。"""
    step_at, tm, pre, post = _timeline(samples, step_at, base_ms)
    if len(pre) < 2:
        return {"steady": False, "elapsed_ms": 0, "amplitude": 0, "reason": "not-enough-baseline"}
    if len(post) < min_settled:
        return {"steady": False, "elapsed_ms": tm(post[-1]) - step_at if post else 0, "amplitude": 0,
                "reason": "not-enough-post-step"}
    dpre, dpost = _denoise(pre), _denoise(post)
    base_noise = _std([s["actual"] for s in pre])
    y0 = _trimmed_avg(dpre)
    amp = max(dpost) - min([y0] + dpost)
    need = max(window_ms, _interval(post, tm) * 10, min_observe_ms)
    last = tm(post[-1])
    el = last - step_at
    if el < need:
        return {"steady": False, "elapsed_ms": el, "amplitude": amp, "reason": "warming-up"}
    if not math.isfinite(amp) or amp <= 0.2 * unit:
        return {"steady": False, "elapsed_ms": el, "amplitude": amp, "reason": "too-little-motion"}
    idx = [i for i, s in enumerate(post) if tm(s) >= last - window_ms]
    if len(idx) < min_settled:
        return {"steady": False, "elapsed_ms": el, "amplitude": amp, "reason": "not-enough-recent-samples"}
    rv = [dpost[i] for i in idx]
    raw = [post[i]["actual"] for i in idx]
    rng = max(rv) - min(rv)
    k = max(1, len(rv) // 2)
    drift = abs(_trimmed_avg(rv[k:]) - _trimmed_avg(rv[:k]))
    noise = _std(raw)
    steady = (rng <= max(amp * 0.25, noise * 3, base_noise * 6, 0.12 * unit)
              and drift <= max(amp * 0.05, noise * 0.85, base_noise * 3, 0.05 * unit)
              and noise <= max(amp * 0.55, base_noise * 10, 0.35 * unit))
    return {"steady": steady, "elapsed_ms": el, "amplitude": amp, "reason": "steady" if steady else "still-drifting",
            "noise": noise, "drift": drift}


def _to_pid(kp, ti_s, td_s):
    ti = max(ti_s, 0.05)
    return {"p": normalize_float(_clamp(kp, 0, 500)), "i": normalize_float(_clamp(kp / ti, 0, 500)),
            "d": normalize_float(_clamp(kp * max(td_s, 0), 0, 500))}


def estimate_pid_from_step(samples, step_at: float, step_output: float, base_ms: float = 350,
                           tail_ms: float = 700, min_delta: float = 0.2) -> dict:
    """原 estimatePidFromStepResponse：开环阶跃 → 10%/63.2% 两点法 FOPDT → 保守 λ（IMC）整定。
    min_delta 原为写死的 0.2，这里做成参数（默认不变）。"""
    step_at, tm, pre, post = _timeline(samples, step_at, base_ms)
    if len(pre) + len(post) < 8:
        raise IdentError("辨识采样点不足，请延长测试时间")
    if len(pre) < 2 or len(post) < 4:
        raise IdentError("无法提取足够的阶跃响应数据")
    dpost = _median_denoise(post, 1)
    y0 = _trimmed_avg([s["actual"] for s in pre])
    last = tm(post[-1])
    y1 = _trimmed_avg([s["actual"] for s in post if last - tm(s) <= tail_ms])
    dy = y1 - y0
    if not math.isfinite(dy) or dy <= min_delta:
        raise IdentError("反馈变化过小，无法可靠计算 PID 初值")
    if step_output <= 0:
        raise IdentError("阶跃输出必须大于 0")
    K = dy / step_output
    i10 = next((i for i, v in enumerate(dpost) if v >= y0 + dy * 0.1), None)
    i63 = next((i for i, v in enumerate(dpost) if v >= y0 + dy * 0.632), None)
    if i10 is None or i63 is None:
        raise IdentError("响应曲线未达到有效阈值，无法估算动态参数")
    t10, t63 = tm(post[i10]) - step_at, tm(post[i63]) - step_at
    tau = max((t63 - t10) / 0.895, 120)
    L = max(t10 - tau * 0.105, 0)
    lam = max(L * CONSERVATIVE_LAMBDA_DEAD_TIME_FACTOR, tau * CONSERVATIVE_LAMBDA_TIME_CONSTANT_FACTOR,
              CONSERVATIVE_LAMBDA_MIN_MS)
    kp = (tau + 0.5 * L) / (K * (lam + 0.5 * L))
    ti = max((tau + 0.5 * L) / 1000 * CONSERVATIVE_INTEGRAL_TIME_FACTOR, CONSERVATIVE_INTEGRAL_TIME_MIN_SECONDS)
    td = (tau * L) / max(2 * tau + L, 1) / 1000 * CONSERVATIVE_DERIVATIVE_TIME_FACTOR
    return {"pid": _to_pid(kp, ti, td), "method": "open-loop-step", "step_output": normalize_float(step_output),
            "y0": normalize_float(y0), "y1": normalize_float(y1), "K": normalize_float(K),
            "dead_ms": round(L), "tau_ms": round(tau)}
