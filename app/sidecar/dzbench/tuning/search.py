"""仿真里的 PID 搜索：PSO 粒子群 / 分阶段（P→I→D→微调），实机只拿 top-k 候选逐个验证。

算法本体是 PID_Helper（GPL-3.0）的移植：third_party/vendored/pid_helper/pid_helper_pso.py（见 SOURCE.md）。
本文件只做：kp/ki/kd ↔ p/i/d、FOPDT 仿真对象 + 闭环阶跃指标（evaluate）、搜索主循环、门禁。
- PSO：只许 sim=True（agent/experiment.require_swarm），有随机性，固定 rng_seed 可复现。
- 结果只是“候选”：实机上每个都要走 TuneGuard / 提议确认，不在这里写参数。
"""
from __future__ import annotations

import math
import random

from . import identify  # noqa: F401  确保 vendored 路径已加进 sys.path
import pid_helper_pso as PSO  # noqa: E402

from ..agent.experiment import require_swarm

MAP = {"kp": "p", "ki": "i", "kd": "d"}


def _to(g: dict) -> dict:
    return {MAP[k]: float(g.get(k, 0.0)) for k in MAP}


def _from(p: dict) -> dict:
    return {k: p[v] for k, v in MAP.items()}


def simulate_fopdt(gains: dict, K: float, T: float, L: float, *, dt: float = 0.005, t_end: float | None = None,
                   u_lim: float = 1.0, r: float = 1.0) -> dict:
    """一阶惯性 + 纯滞后对象，位置式 PID（微分走测量、积分限幅防饱和），单位阶跃 → 指标（与打分同键）。"""
    t_end = t_end or max(10 * (T + L), 1.0)
    n, nd = int(t_end / dt), max(0, int(round(L / dt)))
    kp, ki, kd = gains.get("kp", 0.0), gains.get("ki", 0.0), gains.get("kd", 0.0)
    y, integ, y_prev = 0.0, 0.0, 0.0
    buf = [0.0] * (nd + 1)
    ys, us = [], []
    for _ in range(n):
        e = r - y
        integ = max(-u_lim, min(u_lim, integ + ki * e * dt))
        u = max(-u_lim, min(u_lim, kp * e + integ - kd * (y - y_prev) / dt))
        y_prev = y
        buf.append(u)
        ud = buf.pop(0)
        y += dt / T * (K * ud - y)
        if not math.isfinite(y) or abs(y) > 1e6:
            return {"itae": 1e6, "overshoot": 10.0, "settling_ms": t_end * 1000, "steady_error": 10.0, "control_ripple": 10.0}
        ys.append(y)
        us.append(u)
    itae = sum((i * dt) * abs(r - v) * dt for i, v in enumerate(ys))
    over = max(0.0, (max(ys) - r) / abs(r))
    band = 0.02 * abs(r)
    last_out = max((i for i, v in enumerate(ys) if abs(v - r) > band), default=-1)
    settle = (last_out + 1) * dt * 1000
    tail = ys[int(0.9 * n):]
    sse = abs(r - sum(tail) / len(tail)) / abs(r)
    du = [abs(us[i] - us[i - 1]) for i in range(n // 2 + 1, n)]
    ripple = sum(du) / max(1, len(du)) / max(u_lim, 1e-9)
    return {"itae": round(itae, 5), "overshoot": round(over, 5), "settling_ms": round(settle, 1),
            "steady_error": round(sse, 5), "control_ripple": round(ripple, 6)}


def optimize(evaluate, seed: dict, *, strategy: str = "pso", sim: bool, iterations: int = 12, swarm: int = 8,
             profile: str = "balanced", top_k: int = 3, rng_seed: int = 0, bounds: dict | None = None) -> dict:
    """evaluate(gains{kp,ki,kd}) → 指标 dict。返回 {baseline, best, top[k], evals, strategy}；score 越小越好，1.0 = 和初值一样。"""
    if strategy == "pso":
        require_swarm(sim)
    elif strategy != "staged":
        raise ValueError(f"strategy 只能 pso / staged，不是 {strategy!r}")
    if profile not in PSO.PROFILES:
        raise ValueError(f"profile 只能 {'/'.join(PSO.PROFILES)}")
    rnd = random.Random(rng_seed).random
    s0 = _to(seed)
    base = evaluate(_from(s0))
    seen: dict[tuple, dict] = {}

    def ev(p: dict) -> float:
        key = tuple(round(p[k], 6) for k in PSO.KEYS)
        if key not in seen:
            m = evaluate(_from(p))
            seen[key] = {"gains": _from(p), "metrics": m, "score": PSO.score(m, base, profile)}
        return seen[key]["score"]

    ev(s0)
    if strategy == "pso":
        pb = {MAP[k]: tuple(v) for k, v in bounds.items()} if bounds else None
        opt = PSO.default_options(s0, swarm, pos_bounds=pb)
        sw = PSO.create_swarm(s0, opt, rnd)
        gbest, gscore = dict(s0), ev(s0)
        for _ in range(iterations):
            sw = [PSO.record_score(pt, ev(pt["position"])) for pt in sw]
            for pt in sw:
                if pt["best_score"] < gscore:
                    gbest, gscore = dict(pt["best_position"]), pt["best_score"]
            sw = PSO.advance(sw, gbest, opt, rnd)
    else:
        cur, cs = dict(s0), ev(s0)
        for stage in ("p", "i", "d", "micro"):
            for _ in range(max(1, iterations // 4)):
                cands = PSO.micro_candidates(cur) if stage == "micro" else PSO.staged_candidates(stage, cur)
                if bounds:
                    cands = [c for c in cands if all(bounds[k][0] <= c[v] <= bounds[k][1] for k, v in MAP.items() if k in bounds)]
                best = min(cands, key=ev, default=None)
                if best is None or ev(best) >= cs:
                    break
                cur, cs = best, ev(best)
    ranked = sorted(seen.values(), key=lambda x: x["score"])
    return {"strategy": strategy, "profile": profile, "evals": len(seen), "baseline": {"gains": dict(seed), "metrics": base},
            "best": ranked[0], "top": ranked[:top_k],
            "note": "仿真候选：实机逐个验证，每个都过护栏/人工确认" if sim else "实机候选：每个都过护栏/人工确认"}
