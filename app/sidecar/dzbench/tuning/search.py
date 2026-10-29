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
             profile: str = "balanced", top_k: int = 3, rng_seed: int = 0, bounds: dict | None = None,
             wide: bool = False) -> dict:
    """wide=False（默认）= PID_Helper 原版：只在初值附近搜；wide=True = 宽范围：PSO 边界放到初值的 0–4 倍（至少 kp≤1/ki≤0.5/kd≤0.1）、
    分阶段每步 ±25/50/100%。evaluate(gains{kp,ki,kd}) → 指标 dict。返回 {baseline, best, top[k], evals, strategy}；score 越小越好，1.0 = 和初值一样。"""
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
        if pb is None and wide:
            pb = {"p": (0.0, max(4 * s0["p"], 1.0)), "i": (0.0, max(4 * s0["i"], 0.5)), "d": (0.0, max(4 * s0["d"], 0.1))}
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
                cands = PSO.micro_candidates(cur) if stage == "micro" else PSO.staged_candidates(stage, cur, pcts=[25, 50, 100] if wide else None)
                if bounds:
                    cands = [c for c in cands if all(bounds[k][0] <= c[v] <= bounds[k][1] for k, v in MAP.items() if k in bounds)]
                best = min(cands, key=ev, default=None)
                if best is None or ev(best) >= cs:
                    break
                cur, cs = best, ev(best)
    ranked = sorted(seen.values(), key=lambda x: x["score"])
    return {"strategy": strategy, "profile": profile, "wide": wide, "evals": len(seen), "baseline": {"gains": dict(seed), "metrics": base},
            "best": ranked[0], "top": ranked[:top_k],
            "note": "仿真候选：实机逐个验证，每个都过护栏/人工确认" if sim else "实机候选：每个都过护栏/人工确认"}


def search_from_step(t: list[float], y: list[float], u: list[float], seed: dict | None = None, **kw) -> dict:
    """开环阶跃数据（控制量 u 跳一下）→ identify.open_loop_pid 得 FOPDT → 在该模型上仿真搜索。
    seed 缺省用辨识出的保守 λ 初值。返回 optimize 的结果 + model。"""
    from .identify import open_loop_pid
    if len(t) < 10 or len(u) != len(t):
        raise ValueError("数据太少：先在开环下给控制量一个台阶，录 2–5 s")
    k = max(range(1, len(u)), key=lambda i: abs(u[i] - u[i - 1]))
    du = u[k] - u[k - 1]
    if abs(du) < 1e-9:
        raise ValueError("控制量没有跳变：先开环给一个台阶")
    m = open_loop_pid(t, y, t[k], du, u)
    K, T, L = m["K"], max(m["tau_s"], 1e-3), max(m["dead_s"], 0.0)
    if K < 0:
        raise ValueError("辨识出的增益为负：反馈方向和控制量相反，先做极性检查")
    src = "board" if seed and any(seed.values()) else "identify"
    if src == "identify":
        seed = {"kp": m["pid"]["p"], "ki": m["pid"]["i"], "kd": m["pid"]["d"]}
    u_lim = max(abs(x) for x in u) * 1.5 or 1.0
    dt = max(min(T / 50, 0.01), 1e-4)
    r = abs(m["y1"] - m["y0"]) or 1.0          # 仿真目标 = 实验台阶的输出变化量（执行器够得着的幅度）
    ev = lambda g: simulate_fopdt(g, K, T, L, dt=dt, u_lim=u_lim, r=r)
    return optimize(ev, seed, sim=True, **kw) | {"model": {"K": K, "tau_s": T, "dead_s": L, "seed_from": src}}
