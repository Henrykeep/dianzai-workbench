"""PID_Helper 的 PSO 粒子群 + 分阶段候选 + 综合打分，逐函数移植到 Python。

Source: gitee.com/qianmonai/PID_Helper@17813ca src/shared/pid-pso.ts
Source: gitee.com/qianmonai/PID_Helper@17813ca src/shared/pid-optimizer.ts（分阶段候选、打分权重、calculateOptimizationScore）
License: GPL-3.0-or-later（见同目录 LICENSE）。改动见 SOURCE.md。

PID 是 dict {"p","i","d"}；指标是 dict {"itae","overshoot","settling_ms","steady_error","control_ripple"}。
"""
from __future__ import annotations

import random as _random

KEYS = ("p", "i", "d")


def clamp(v, lo, hi):
    return min(hi, max(lo, v))


def _r(x, n=3):
    return round(x, n)


def clamp_pid(pid, bounds):
    return {k: _r(clamp(pid[k], *bounds[k])) for k in KEYS}


def _init_bounds(seed, pb):
    def around(v, dec, inc, fdec, finc, b):
        ds, is_ = max(abs(v) * dec, fdec), max(abs(v) * inc, finc)
        return (_r(clamp(v - ds, *b)), _r(clamp(v + is_, *b)))
    return {"p": around(seed["p"], 0.35, 0.2, 0.18, 0.1, pb["p"]),
            "i": around(seed["i"], 0.45, 0.15, 0.12, 0.06, pb["i"]),
            "d": around(seed["d"], 0.35, 0.2, 0.025, 0.015, pb["d"])}


def position_bounds(seed, minimum=None):
    m = minimum or {}
    return {"p": (_r(m.get("p", 0)), _r(max(seed["p"] * 1.75 + 0.35, m.get("p", 0) + 0.45))),
            "i": (_r(m.get("i", 0)), _r(max(seed["i"] * 1.55 + 0.18, m.get("i", 0) + 0.25))),
            "d": (_r(m.get("d", 0)), _r(max(seed["d"] * 1.6 + 0.04, m.get("d", 0) + 0.06)))}


def velocity_bounds(b):
    out = {}
    for k, (lo, hi) in b.items():
        v = _r(max(hi - lo, 0.02) * 0.055)
        out[k] = (-v, v)
    return out


def default_options(seed, swarm_size, minimum=None, pos_bounds=None):
    """原版 createDefaultPsoOptions；pos_bounds 可由调用方给（原版按 seed 推算，量纲是电机转速）。"""
    pb = pos_bounds or position_bounds(seed, minimum)
    return {"swarm_size": swarm_size, "inertia": 0.45, "cognitive": 0.9, "social": 0.95,
            "position_bounds": pb, "velocity_bounds": velocity_bounds(pb)}


def create_swarm(seed, opt, rnd=_random.random):
    ib = _init_bounds(seed, opt["position_bounds"])
    sw = []
    for i in range(opt["swarm_size"]):
        if i == 0:
            pos, vel = clamp_pid(seed, opt["position_bounds"]), {k: 0.0 for k in KEYS}
        else:
            pos = clamp_pid({k: ib[k][0] + (ib[k][1] - ib[k][0]) * rnd() for k in KEYS}, opt["position_bounds"])
            vel = {k: _r(opt["velocity_bounds"][k][0] + (opt["velocity_bounds"][k][1] - opt["velocity_bounds"][k][0]) * rnd()) for k in KEYS}
        sw.append({"id": f"particle-{i + 1}", "position": pos, "velocity": vel, "best_position": dict(pos),
                   "best_score": float("inf"), "score": None})
    return sw


def record_score(pt, score):
    imp = score < pt["best_score"]
    return pt | {"score": score, "best_score": score if imp else pt["best_score"],
                 "best_position": dict(pt["position"] if imp else pt["best_position"])}


def advance(swarm, gbest, opt, rnd=_random.random):
    out = []
    for pt in swarm:
        v = {k: _r(clamp(opt["inertia"] * pt["velocity"][k]
                         + opt["cognitive"] * rnd() * (pt["best_position"][k] - pt["position"][k])
                         + opt["social"] * rnd() * (gbest[k] - pt["position"][k]), *opt["velocity_bounds"][k])) for k in KEYS}
        pos = clamp_pid({k: pt["position"][k] + v[k] for k in KEYS}, opt["position_bounds"])
        out.append(pt | {"position": pos, "velocity": v, "best_position": dict(pt["best_position"])})
    return out


# ---- 分阶段（pid-optimizer.ts）
DEFAULT_STAGED_PERCENT = {"p": [10, 15, 20], "i": [10, 15, 20], "d": [10, 15, 20]}
DEFAULT_MICRO_PERCENT = 5


def staged_ratios(pcts):
    s, m, l = sorted(clamp(float(x), 0, 100) for x in pcts[:3])
    return [round(1 + x / 100, 6) for x in (-l, -m, -s, s, m, l)]


def _uniq(cands, cur):
    seen, out = set(), []
    for c in cands:
        key = (round(c["p"], 3), round(c["i"], 6), round(c["d"], 6))
        if key in seen or c == cur:
            continue
        seen.add(key)
        out.append(c)
    return out


def staged_candidates(field, cur, minimum=None, pcts=None, hi=500):
    m = minimum or {"p": 0, "i": 0, "d": 0}
    rs = staged_ratios(pcts or DEFAULT_STAGED_PERCENT[field])
    if field == "p":
        base, nd = cur["p"], 3
    elif field == "i":
        base, nd = max(cur["i"], cur["p"] * 0.02, m["i"] + 0.005), 6
    else:
        base, nd = max(cur["d"], cur["p"] * 0.005, m["d"] + 0.002), 6
    c = [{k: (round(clamp(base * r, m[k], hi), nd) if k == field else clamp(cur[k], m[k], hi)) for k in KEYS} for r in rs]
    return _uniq(c, cur)


def micro_candidates(cur, minimum=None, pct=DEFAULT_MICRO_PERCENT, hi=500):
    m = minimum or {"p": 0, "i": 0, "d": 0}
    pct = clamp(pct, 0, 50)
    if pct <= 0:
        return []
    c = []
    for k in KEYS:
        for r in (1 - pct / 100, 1 + pct / 100):
            x = dict(cur)
            x[k] = cur[k] * r
            c.append({"p": round(clamp(x["p"], m["p"], hi), 3), "i": round(clamp(x["i"], m["i"], hi), 6),
                      "d": round(clamp(x["d"], m["d"], hi), 6)})
    return _uniq(c, cur)


# ---- 打分
PROFILES = {
    "balanced": {"itae": 0.45, "overshoot": 0.2, "settling": 0.2, "steady_error": 0.1, "control_ripple": 0.05},
    "conservative": {"itae": 0.35, "overshoot": 0.3, "settling": 0.15, "steady_error": 0.1, "control_ripple": 0.1},
    "actuator-friendly": {"itae": 0.3, "overshoot": 0.2, "settling": 0.15, "steady_error": 0.1, "control_ripple": 0.25},
}
FLOORS = {"itae": 0.05, "overshoot": 0.02, "settling_ms": 100, "steady_error": 0.02, "control_ripple": 0.02}


def score(m, base, profile="balanced"):
    """原版 calculateOptimizationScore：每项 (候选+地板)/(基线+地板) 加权；1.0 = 和基线一样，越小越好。"""
    w = PROFILES[profile]
    n = lambda k: (m[k] + FLOORS[k]) / (base[k] + FLOORS[k])
    return round(n("itae") * w["itae"] + n("overshoot") * w["overshoot"] + n("settling_ms") * w["settling"]
                 + n("steady_error") * w["steady_error"] + n("control_ripple") * w["control_ripple"], 4)
