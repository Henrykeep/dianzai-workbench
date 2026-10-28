"""调参基准（固定随机种子）：baseline / rules（无 LLM）/ llm（可注入假 LLM）三路在同一个对象模型上比较。

思路参考 llm-pid-tuner（MIT）的 benchmark.py；对象模型、指标和统计为自写。
对象：一阶惯性 + 纯滞后 + 测量噪声的速度环（类似 car_2wd 一个轮子），PI 控制，输出限幅。
统计：达标轮数（None = 未达标）、最终归一化 IAE、越界次数（护栏之外的值，目标 0）。
"""
from __future__ import annotations

import random

from .guard import GuardError, TuneGuard, parse_reply
from .tuning import step_metrics, tuning_hints

DT = 0.002


def plant_step(kp: float, ki: float, seed: int, tau=0.08, delay=0.01, gain=8.0, umax=1.0, amp=2.0, t_end=1.5):
    rnd = random.Random(seed)
    nd = int(delay / DT)
    buf, y, integ = [0.0] * (nd + 1), 0.0, 0.0
    t, ys, sp = [], [], []
    for k in range(int(t_end / DT)):
        r = amp if k * DT >= 0.2 else 0.0
        e = r - (y + rnd.gauss(0, 0.01 * amp))
        u = kp * e + integ
        if abs(u) < umax or (u > 0) != (e > 0):          # 条件积分抗饱和
            integ += ki * e * DT
        u = max(-umax, min(umax, u))
        buf.append(u)
        y += (gain * buf.pop(0) - y) * DT / tau
        t.append(k * DT); ys.append(y); sp.append(r)
    return t, ys, sp


def rule_pick(m, gains: dict, g: TuneGuard, kp="kp", ki="ki", kd=None):
    """无 LLM 模式的单项选择：所有规则建议里，跳过被禁方向；优先换一个与上一轮不同的参数（避免只拧一个旋钮）。"""
    cands = [(k, v) for h in tuning_hints(m, gains, kp, ki, kd) for k, v in h.changes.items()
             if (k, 1 if v > gains.get(k, 0) else -1) not in g.blocked]
    last = g.rounds[-1].changed[0] if g.rounds and g.rounds[-1].changed else None
    cands.sort(key=lambda kv: kv[0] == last)
    return cands[0] if cands else None


def run(policy: str, seed: int = 7, llm=None, sim: bool = False, start: dict | None = None) -> dict:
    gains = dict(start or {"kp": 0.08, "ki": 1.5})      # car_2wd 的起步值
    bounds = {"kp": (0.0, 2.0), "ki": (0.0, 20.0)}
    g = TuneGuard(bounds, sim=sim)
    violations, done_at, last = 0, None, None
    staged = None
    if policy == "staged":
        from .experiment import StagedSearch
        staged = StagedSearch()
    for rnd_ in range(g.profile.max_rounds):
        t, y, sp = plant_step(gains["kp"], gains["ki"], seed + rnd_)
        m = step_metrics(t, y, sp)
        last = m
        v = g.record(m, gains)
        if v["action"] == "done":
            done_at = rnd_ + 1
            break
        if v["action"] == "stop":
            break
        if v["action"] == "rollback" and g.best():
            gains = dict(g.best().gains)
            g.proposed_this_round = None
            continue
        prop = None
        if policy == "rules":
            prop = rule_pick(m, gains, g)
        elif policy == "staged":
            prop = staged.propose(m, gains, g)
        elif policy == "llm":
            try:
                r = parse_reply(llm(m, gains, g))
                prop = (r["param"], r["value"]) if r["action"] == "PROPOSE" else None
            except GuardError:
                prop = None
        if prop:
            try:
                val, _ = g.check(prop[0], gains[prop[0]], prop[1])
            except GuardError:
                continue
            lo, hi = bounds[prop[0]]
            violations += not (lo <= val <= hi)
            gains[prop[0]] = val
    return {"policy": policy, "seed": seed, "rounds_to_good": done_at, "rounds": len(g.rounds),
            "final_iae_norm": round(last.iae / 2.0, 4) if last and last.ok else None, "violations": violations,
            "gains": gains, "stopped": g.stopped}


CASES = {"car_default": {"kp": 0.08, "ki": 1.5}, "aggressive": {"kp": 0.6, "ki": 15.0}, "sluggish": {"kp": 0.03, "ki": 0.3}}


def table(seeds=(1, 7, 42), policies=("baseline", "rules", "staged"), llm=None) -> list[dict]:
    return [run(p, s, llm=llm, sim=sim, start=st) | {"case": c, "sim": sim}
            for c, st in CASES.items() for p in policies + (("llm",) if llm else ()) for s in seeds for sim in (False, True)]


if __name__ == "__main__":
    for r in table():
        print(r["case"], r["policy"], "sim" if r["sim"] else "hw ", r["seed"], r["rounds_to_good"], r["final_iae_norm"], r["violations"], r["gains"])
