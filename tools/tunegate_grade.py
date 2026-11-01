#!/usr/bin/env python3
"""tunegate 唯一的判卷模块：只有这里读 plant.json / 真值 / feasible 标签（tools/check_no_truth_leak.py 守着）。

整定器（dzbench.tuning.autotune）只读 app.yaml / link.yaml / spec.txt；tools/tunegate.py 只拿这里给的仿真板和判卷结果。
可行性三态（fw-feas #124，docs/dev/randplant-feasible.md）：feasible ∈ True / False / "unknown"，复核走 tools/feascheck.py judge()。
桶：ok / fail / false_pass（硬红）/ truth_label_suspect（标签 false 但复核找到达标参数：标签错，不算后端假达标）/
undecided（unknown 复核仍不定，不进通过率）。
"""
from __future__ import annotations

import json
import pathlib

NEAR_REF = 1.5      # 最好一轮真值代价 ≤ reference × 1.5 + 0.02
NEAR_ABS = 0.02


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
    _, ci = truth(res["initial"]["roles"] if "roles" in res["initial"] else {dd["role"]: dd["init"] for dd in app["params"]})
    _, cb = truth(res["best"]["roles"])
    # 假达标按整定器自己那次实验（同幅度、同窗口、无噪声的真对象）判
    ea, en = float(res.get("amp") or ref["amp"]), int(res.get("n") or ref["n"])
    te, re_, ye, _ = RP.simulate(plant, m, res["best"]["roles"], ea, en)
    me = AT.metrics(te, re_, ye, ea)
    sp = AT.parse_spec(spec)
    truth_ok = not AT.meets(me, sp)
    f, v = plant["feasible"], res["verdict"]
    errs, bucket = [], "ok"
    if v == "pass" and res.get("amp_reduced"):                       # #129：降幅测的不许给 pass
        errs.append(f"假达标：按降幅 {res.get('amp_tested')} 测（题面 {res.get('amp_spec')}）却给了 pass")
    if v == "pass" and not truth_ok:
        errs.append("假达标：卡上 pass，真值不满足 " + "、".join(AT.meets(me, sp)))
    unchanged = bool(res.get("unchanged"))
    if f is True and v != "pass" and res.get("stop_reason") == "converged":
        errs.append("提前停：报收敛却未达标（feasible 对象，硬门禁）")
    if f is True and not (unchanged and v == "pass" and truth_ok):  # 初值已达标：只按题面判，不要求“比初值好”
        if not cb < ci and ci < 1e9:
            errs.append(f"没比初值好（真值代价 {cb:.4g} ≥ 初值 {ci:.4g}）")
        if not cb <= ref["cost"] * NEAR_REF + NEAR_ABS:
            errs.append(f"离 reference 太远（{cb:.4g} > {ref['cost']:.4g}×{NEAR_REF}+{NEAR_ABS}）")
    elif f is False:
        if v == "pass" and truth_ok:
            if _recheck(plant, seed, v, truth_ok, source) == "ok":
                bucket = "truth_label_suspect"                       # 标签说做不到，复核找到达标参数：标签错，卡片对
            else:
                errs.append(f"假达标：feasible:false（{plant['infeasible_reason']}）却给了 pass")
        elif v != "pass" and plant["infeasible_reason"] in ("saturation", "delay", "nonminimum_phase") \
                and res["category"] != plant["infeasible_reason"]:
            errs.append(f"原因对不上：应为 {plant['infeasible_reason']}，卡上 {res['category']}（{res['pass_basis']}）")
    elif not (v == "pass" and truth_ok) and _recheck(plant, seed, v, truth_ok, source) == "undecided":   # "unknown"
        bucket = "undecided"
    if v == "pass" and errs and not any(e.startswith("假达标") for e in errs):
        # 整定器说达标、判卷不认（比初值差 / 离参考太远 / 原因对不上）：算假达标的一个子项
        errs.insert(0, "假达标（整定器说达标、判卷不认）：" + "；".join(errs))
    claims = v == "pass" and bool(errs)
    fake = any(e.startswith("假达标") for e in errs)
    early = any(e.startswith("提前停") for e in errs)
    if fake:
        bucket = "false_pass"
    elif early:
        bucket = "early_stop_not_pass"
    elif errs:
        bucket = "fail"
    return {"seed": seed, "kind": plant["kind"], "feasible": f, "cause": plant["infeasible_reason"],
            "verdict": v, "category": res["category"], "pass_basis": res["pass_basis"],
            "cost": {"initial": ci, "best": cb, "reference": ref["cost"]}, "ok": not errs, "errors": errs,
            "false_pass": fake, "claims_pass_grader_fails": claims, "early_stop_not_pass": early, "bucket": bucket,
            "stop_reason": res.get("stop_reason"), "unchanged": unchanged}


def line(r: dict) -> str:
    """单个 seed 的一行（含真值标签，所以只在判卷模块里拼）。"""
    import math
    cost = {k: round(v, 4) if math.isfinite(v) else None for k, v in (r.get("cost") or {}).items()}
    return (f"{'✓' if r['ok'] else '✗'} seed={r['seed']} {r.get('kind', '?')} feasible={r.get('feasible')} "
            f"verdict={r.get('verdict')}/{r.get('category')}{' 说达标判卷不认' if r.get('claims_pass_grader_fails') else ''} stop={r.get('stop_reason')}{' unchanged' if r.get('unchanged') else ''} "
            f"cost {json.dumps(cost)} {'; '.join(r.get('errors') or [])}")


def summarize(rs: list[dict]) -> dict:
    """汇总（按真值标签分桶，所以只在判卷模块里做）：通过率（全部 / 只算可行）、假达标、提前停未达标、unknown 比例、各原因类别计数。"""
    und = [r for r in rs if r.get("bucket") == "undecided"]
    bad = [r for r in rs if not r["ok"]]
    feas = [r for r in rs if r.get("feasible") is True]
    infe = [r for r in rs if r.get("feasible") is False]
    unk = [r for r in rs if r.get("feasible") == "unknown"]
    cats: dict = {}
    for r in infe:
        c = cats.setdefault(r.get("cause") or "?", {"n": 0, "cause_ok": 0})
        c["n"] += 1
        c["cause_ok"] += int(r.get("category") == r.get("cause"))
    den = len(rs) - len(und)
    return {"n": len(rs), "den": den, "good": den - len(bad), "bad": [r["seed"] for r in bad],
            "n_feas": len(feas), "feas_good": sum(1 for r in feas if r["ok"]), "n_infeas": len(infe),
            "unknown": [r["seed"] for r in unk], "unknown_ratio": (len(unk) / len(rs)) if rs else 0.0,
            "undecided": [r["seed"] for r in und],
            "false_pass": [r["seed"] for r in rs if r.get("false_pass")],
            "claims_pass_grader_fails": [r["seed"] for r in rs if r.get("claims_pass_grader_fails")],   # 已含在 false_pass 里
            "early_stop_not_pass": [r["seed"] for r in rs if r.get("early_stop_not_pass")],
            "truth_label_suspect": [r["seed"] for r in rs if r.get("bucket") == "truth_label_suspect"],
            "unchanged": [r["seed"] for r in rs if r.get("unchanged")],
            "per_category": cats}
