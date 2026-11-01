#!/usr/bin/env python3
"""tunegate 唯一的判卷模块：只有这里读 plant.json / 真值 / feasible 标签（tools/check_no_truth_leak.py 守着）。

整定器（dzbench.tuning.autotune）只读 app.yaml / link.yaml / spec.txt；tools/tunegate.py 只拿这里给的仿真板和判卷结果。
可行性三态（fw-feas #124，docs/dev/randplant-feasible.md）：feasible ∈ True / False / "unknown"，复核走 tools/feascheck.py judge()。
桶：ok / fail / false_pass（硬红）/ truth_label_suspect（标签 false 但复核找到达标参数：标签错，不算后端假达标）/
undecided（unknown 复核仍不定，不进通过率）。
"""
from __future__ import annotations

import json
import math
import pathlib

import numpy as np

NEAR_REF = 1.5      # 最好一轮真值代价 ≤ reference × 1.5 + 0.02
NEAR_ABS = 0.02

# 带噪真值判卷（fw-scorer-noisy）：对象照 randplant 的 noise_std 加传感器噪声闭环仿真，控制器看到带噪测量，
# 代价按加噪前的真输出算。噪声种子是判卷专用的 K 个固定值（与仿真板 seed+104729、整定器 seed 都无关），结果确定。
# 聚合取 K 次的均值（AGG="mean"）；p75 更严，作为诊断字段一并给出。noise_std=0 的对象只跑一次（与无噪一致）。
NOISE_K = 8
NOISE_SEEDS = tuple(0x5C0_0000 + k for k in range(NOISE_K))
REF_TRIES = 48       # 带噪参考：在无噪参考 / 其 kd 缩放 / 初值上再做乘性局部搜索的次数


def _sat_frac(u, p: dict, u_max: float) -> float:
    lim = min(u_max, float(p["ulim"])) if p.get("ulim") else u_max
    u = np.asarray(u, float)
    return float(np.mean(np.abs(u) >= lim * (1 - 1e-9))) if len(u) and lim > 0 else 0.0


def noisy_truth(plant: dict, m, p: dict, amp: float, n: int) -> dict:
    """K 个判卷专用噪声种子下的带噪闭环：cost = 真输出代价均值（判卷用）；p75 = 更严的诊断；
    observed = 按带噪测量 y 算的代价均值（整定器看到的条件，只作对照、不参与判卷）；sat_frac = 执行器饱和时间占比均值。"""
    import tunegate_plant as TP
    from dzbench.tuning import autotune as AT
    seeds = NOISE_SEEDS if plant.get("noise_std") else NOISE_SEEDS[:1]
    ct, co, sf, mets = [], [], [], []
    for s in seeds:
        t, r, yt, ym, u = TP.simulate_noisy(plant, m, p, amp, n, np.random.default_rng(s))
        mt = AT.metrics(t, r, yt, amp)
        ct.append(AT.cost(mt))
        co.append(AT.cost(AT.metrics(t, r, ym, amp)))
        sf.append(_sat_frac(u, p, plant["u_max"]))
        mets.append(mt)
    return {"cost": float(np.mean(ct)), "p75": float(np.percentile(ct, 75)), "observed": float(np.mean(co)),
            "sat_frac": float(np.mean(sf)), "k": len(seeds), "metrics": mets}


def reference_noisy(plant: dict, m, app: dict, ref: dict) -> dict:
    """带噪真值下的参考代价：候选 = 无噪参考参数（及其 kd×{1,0.5,0.25,0}）+ 初值，再在声明范围内乘性局部搜索。
    对所有对象同一流程，种子固定（plant seed + 4242）。"""
    from dzbench.tuning import autotune as AT
    decl = [dict(d) for d in app["params"]]
    amp, n = ref["amp"], ref["n"]
    base = ref.get("params_roles") or {d["role"]: d["init"] for d in decl}
    cands = [dict(base, kd=base["kd"] * k) for k in (1.0, 0.5, 0.25, 0.0)] if "kd" in base else [dict(base)]
    cands.append({d["role"]: d["init"] for d in decl})
    best, bc = None, math.inf
    for c in cands:
        c = AT._clip(c, decl)
        cc = noisy_truth(plant, m, c, amp, n)["cost"]
        if cc < bc:
            best, bc = c, cc
    rng = np.random.default_rng(int(plant.get("seed", 0)) + 4242)
    for _ in range(REF_TRIES if plant.get("noise_std") else 0):
        c = AT._clip({k: v * float(math.exp(rng.normal(0, 0.35))) for k, v in best.items()}, decl)
        cc = noisy_truth(plant, m, c, amp, n)["cost"]
        if cc < bc:
            best, bc = c, cc
    return {"params_roles": best, "cost": bc}


def _rp(source: str):
    if source == "randplant":
        import tunegate_plant as RP
    else:
        import randplant_standin as RP
    return RP


def load(d) -> dict:
    return json.loads((pathlib.Path(d) / "plant.json").read_text("utf-8"))


def board(d, app: dict, seed: int, source: str):
    return _rp(source).SimBoard(load(d), app, seed)


def _recheck(plant: dict, seed: int, verdict: str, truth_ok: bool, source: str) -> str:
    if source != "randplant":
        return "ok"
    import feascheck
    import randplant
    return feascheck.judge(randplant.gen(seed, "1-3", plant.get("gen_kind", "any")), verdict, truth_ok)


def grade(d, seed: int, res: dict, app: dict, spec: str, source: str = "randplant") -> dict:
    import control
    from dzbench.tuning import autotune as AT
    RP = _rp(source)
    plant = load(d)
    ref = plant["reference"]
    m = AT.LinModel(control.c2d(control.tf(plant["num"], plant["den"]), plant["sample_s"]), round(plant["delay_s"] / plant["sample_s"]))

    def truth(p):
        t, r, y, u = RP.simulate(plant, m, p, ref["amp"], ref["n"])
        mm = AT.metrics(t, r, y, ref["amp"])
        return mm, AT.cost(mm)
    pi = res["initial"]["roles"] if "roles" in res["initial"] else {dd["role"]: dd["init"] for dd in app["params"]}
    pb = res["best"]["roles"]
    _, ci0 = truth(pi)                      # 无噪真值：只作诊断
    _, cb0 = truth(pb)
    ni, nb = noisy_truth(plant, m, pi, ref["amp"], ref["n"]), noisy_truth(plant, m, pb, ref["amp"], ref["n"])
    rn = reference_noisy(plant, m, app, ref)
    ci, cb = ni["cost"], nb["cost"]         # 判「比初值好」「接近参考」用带噪真值
    ref_cost = rn["cost"]
    # 假达标按整定器自己那次实验（同幅度、同窗口、无噪声的真对象）判
    ea, en = float(res.get("amp") or ref["amp"]), int(res.get("n") or ref["n"])
    te, re_, ye, _ = RP.simulate(plant, m, res["best"]["roles"], ea, en)
    me = AT.metrics(te, re_, ye, ea)
    sp = AT.parse_spec(spec)
    # 假达标：无噪真值和带噪真值（K 次都要）两边都得满足题面
    ne = noisy_truth(plant, m, res["best"]["roles"], ea, en)
    miss = list(dict.fromkeys(AT.meets(me, sp) + [k + "(带噪)" for mm in ne["metrics"] for k in AT.meets(mm, sp)]))
    truth_ok = not miss
    f, v = plant["feasible"], res["verdict"]
    errs, bucket = [], "ok"
    if v == "pass" and res.get("amp_reduced"):                       # #129：降幅测的不许给 pass
        errs.append(f"假达标：按降幅 {res.get('amp_tested')} 测（题面 {res.get('amp_spec')}）却给了 pass")
    if v == "pass" and not truth_ok:
        errs.append("假达标：卡上 pass，真值不满足 " + "、".join(miss))
    if f is True:
        if not cb < ci and ci < 1e9:
            errs.append(f"没比初值好（带噪真值代价 {cb:.4g} ≥ 初值 {ci:.4g}）")
        if not cb <= ref_cost * NEAR_REF + NEAR_ABS:
            errs.append(f"离 reference 太远（带噪真值 {cb:.4g} > {ref_cost:.4g}×{NEAR_REF}+{NEAR_ABS}）")
    elif f is False:
        if v == "pass" and truth_ok:
            if _recheck(plant, seed, v, truth_ok, source) == "ok":
                bucket = "truth_label_suspect"                       # 标签说做不到，复核找到达标参数：标签错，卡片对
            else:
                errs.append(f"假达标：feasible:false（{plant['infeasible_reason']}）却给了 pass")
        elif v != "pass" and plant["infeasible_reason"] in ("saturation", "delay", "nonminimum_phase") \
                and res["category"] not in (plant["infeasible_reason"], "unconfirmed"):
            errs.append(f"原因对不上：应为 {plant['infeasible_reason']}，卡上 {res['category']}（{res['pass_basis']}）")
    elif not (v == "pass" and truth_ok) and _recheck(plant, seed, v, truth_ok, source) == "undecided":   # "unknown"
        bucket = "undecided"
    fake = any(e.startswith("假达标") for e in errs)
    if fake:
        bucket = "false_pass"
    elif errs:
        bucket = "fail"
    return {"seed": seed, "kind": plant["kind"], "feasible": f, "cause": plant["infeasible_reason"],
            "verdict": v, "category": res["category"], "pass_basis": res["pass_basis"],
            "cost": {"initial": ci, "best": cb, "reference": ref_cost},
            "noisy_truth": {"agg": "mean", "k": ni["k"], "initial_p75": ni["p75"], "best_p75": nb["p75"]},
            "noise_free": {"initial": ci0, "best": cb0, "reference": ref["cost"]},          # 诊断：不参与判卷
            "observed": {"initial": ni["observed"], "best": nb["observed"]},                 # 对照：按带噪测量算，不参与判卷
            "sat_frac": {"initial": ni["sat_frac"], "best": nb["sat_frac"]},                 # 诊断：执行器饱和时间占比
            "ok": not errs, "errors": errs,
            "false_pass": fake, "bucket": bucket}
