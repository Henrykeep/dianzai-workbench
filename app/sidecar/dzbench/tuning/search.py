"""仿真里的 PID 搜索：PSO 粒子群 / 分阶段（P→I→D→微调），实机只拿 top-k 候选逐个验证。

净室实现（只依据公开文献，见 docs/参考来源.md“净室重写算法来源”）：
- PSO：Kennedy & Eberhart 1995，收缩系数版 Clerc & Kennedy 2002（w = 0.7298，c1 = c2 = 1.49618），位置夹在边界内、速度限为边界宽度的 20 %。
- 分阶段：逐坐标模式搜索（Hooke & Jeeves 1961 的探索步），P → I → D → 三者同时微调，步长按百分比乘法放缩。
- 打分：各指标 (x + floor)/(基线 + floor) 的加权平均，1.0 = 和初值一样，越小越好。
本文件只做：kp/ki/kd ↔ p/i/d、FOPDT 仿真对象 + 闭环阶跃指标（evaluate）、搜索主循环、门禁。
- PSO：只许 sim=True（agent/experiment.require_swarm），有随机性，固定 rng_seed 可复现。
- 结果只是“候选”：实机上每个都要走 TuneGuard / 提议确认，不在这里写参数。
"""
from __future__ import annotations

import math
import random


from ..agent.experiment import require_swarm



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


KEYS = ("kp", "ki", "kd")
PROFILES = {
    "balanced":     {"itae": 1.0, "overshoot": 1.0, "settling_ms": 0.5, "steady_error": 1.0, "control_ripple": 0.5},
    "fast":         {"itae": 1.5, "overshoot": 0.5, "settling_ms": 1.0, "steady_error": 1.0, "control_ripple": 0.3},
    "smooth":       {"itae": 0.5, "overshoot": 2.0, "settling_ms": 0.5, "steady_error": 1.0, "control_ripple": 1.5},
}
FLOORS = {"itae": 0.05, "overshoot": 0.02, "settling_ms": 100.0, "steady_error": 0.02, "control_ripple": 0.02}
W, C1, C2 = 0.7298, 1.49618, 1.49618        # Clerc & Kennedy 2002 收缩系数


def score(m: dict, base: dict, profile: str = "balanced") -> float:
    w = PROFILES[profile]
    return sum(w[k] * (m[k] + FLOORS[k]) / (base[k] + FLOORS[k]) for k in w) / sum(w.values())


def _bounds(s0: dict, bounds: dict | None, wide: bool) -> dict:
    if bounds:
        return {k: tuple(map(float, bounds[k])) if k in bounds else (0.0, max(3 * s0[k], 0.1)) for k in KEYS}
    f = 4.0 if wide else 2.0                      # 默认：初值的 0–2 倍；wide：0–4 倍，并保证最小搜索宽度
    mins = {"kp": 1.0, "ki": 0.5, "kd": 0.1} if wide else {"kp": 0.2, "ki": 0.1, "kd": 0.02}
    return {k: (0.0, max(f * s0[k], mins[k])) for k in KEYS}


def optimize(evaluate, seed: dict, *, strategy: str = "pso", sim: bool, iterations: int = 12, swarm: int = 8,
             profile: str = "balanced", top_k: int = 3, rng_seed: int = 0, bounds: dict | None = None,
             wide: bool = False) -> dict:
    """evaluate(gains{kp,ki,kd}) → 指标 dict（simulate_fopdt 同键）。返回 {baseline, best, top[k], evals, strategy}；
    score 越小越好，1.0 = 和初值一样。PSO 只许 sim=True；固定 rng_seed 可复现。"""
    if strategy == "pso":
        require_swarm(sim)
    elif strategy != "staged":
        raise ValueError(f"strategy 只能 pso / staged，不是 {strategy!r}")
    if profile not in PROFILES:
        raise ValueError(f"profile 只能 {'/'.join(PROFILES)}")
    rng = random.Random(rng_seed)
    s0 = {k: float(seed.get(k, 0.0)) for k in KEYS}
    base = evaluate(dict(s0))
    B = _bounds(s0, bounds, wide)
    seen: dict[tuple, dict] = {}

    def clip(g):
        return {k: round(min(B[k][1], max(B[k][0], g[k])), 6) for k in KEYS}

    def ev(g: dict) -> float:
        key = tuple(g[k] for k in KEYS)
        if key not in seen:
            m = evaluate(dict(g))
            seen[key] = {"gains": dict(g), "metrics": m, "score": score(m, base, profile)}
        return seen[key]["score"]

    s0c = clip(s0)
    ev(s0c)
    if strategy == "pso":
        vmax = {k: 0.2 * (B[k][1] - B[k][0]) for k in KEYS}
        xs = [s0c] + [clip({k: rng.uniform(*B[k]) for k in KEYS}) for _ in range(max(1, swarm) - 1)]
        vs = [{k: rng.uniform(-vmax[k], vmax[k]) for k in KEYS} for _ in xs]
        pb = [(dict(x), ev(x)) for x in xs]
        gb = min(pb, key=lambda p: p[1])
        for _ in range(iterations):
            for i, x in enumerate(xs):
                v = {}
                for k in KEYS:
                    vk = W * vs[i][k] + C1 * rng.random() * (pb[i][0][k] - x[k]) + C2 * rng.random() * (gb[0][k] - x[k])
                    v[k] = max(-vmax[k], min(vmax[k], vk))
                vs[i] = v
                xs[i] = clip({k: x[k] + v[k] for k in KEYS})
                sc = ev(xs[i])
                if sc < pb[i][1]:
                    pb[i] = (dict(xs[i]), sc)
                    if sc < gb[1]:
                        gb = pb[i]
    else:
        steps = [0.25, 0.5, 1.0] if wide else [0.1, 0.2]
        cur, cs = s0c, ev(s0c)
        for stage in ("kp", "ki", "kd", "micro"):
            for _ in range(max(1, iterations // 4)):
                cands = []
                if stage == "micro":
                    for k in KEYS:
                        for sg in (-1, 1):
                            cands.append(clip(cur | {k: cur[k] * (1 + sg * 0.05)}))
                else:
                    scale = cur[stage] or 0.1 * (B[stage][1] - B[stage][0])
                    for st in steps:
                        for sg in (-1, 1):
                            cands.append(clip(cur | {stage: cur[stage] + sg * st * scale}))
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
