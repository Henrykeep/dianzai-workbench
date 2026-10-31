#!/usr/bin/env python3
"""#78 随机对象门禁：没见过的被控对象上，后端通用整定（dzbench.tuning.autotune）必须
  - feasible 对象：比初值好，并接近 plant.json reference（同幅度、同时长、无噪声的真值上比代价）；给了 pass 但真值不达标 = 假达标 → 红；
  - feasible:false 对象：verdict 必须是 fail/unknown，原因类别对得上（saturation / delay / nonminimum_phase）；给 pass = 红。
失败一律打印 seed，`tunegate.py --seed N` 单独复现。

对象来源：tools/randplant.py（嵌入式开发-2，sim:randplant-<seed> 板）存在就用它；还没推上来 → 用 tools/randplant_standin.py（STAND-IN，Python 仿真板）。
整定只读 app.yaml / link.yaml / spec.txt，plant.json 只给判卷用。
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app" / "sidecar"))
sys.path.insert(0, str(ROOT / "tools"))

NEAR_REF = 1.5      # 最好一轮真值代价 ≤ reference × 1.5 + 0.02
NEAR_ABS = 0.02


def source() -> str:
    return "randplant" if (ROOT / "tools" / "randplant.py").exists() else "standin"


def one(seed: int, kind: str) -> dict:
    import yaml
    from dzbench.tuning import autotune as AT
    if source() == "randplant":
        raise SystemExit("tools/randplant.py 已存在：sim:randplant-<seed> 板的 Session 适配还没接（#78 第二步），先接上再跑门禁")
    import randplant_standin as RP
    with tempfile.TemporaryDirectory() as d:
        RP.make(seed, kind, d)
        app = yaml.safe_load(open(f"{d}/app.yaml", encoding="utf-8"))
        link = yaml.safe_load(open(f"{d}/link.yaml", encoding="utf-8"))
        spec = open(f"{d}/spec.txt", encoding="utf-8").read()
        plant = json.load(open(f"{d}/plant.json", encoding="utf-8"))          # 只用于判卷
    board = RP.SimBoard(plant, app, seed)
    t0 = time.monotonic()
    res = AT.autotune(board, app, link, spec, seed)
    ref = plant["reference"]
    import control
    m = AT.LinModel(control.c2d(control.tf(plant["num"], plant["den"]), plant["sample_s"]), round(plant["delay_s"] / plant["sample_s"]))

    def truth(p):
        t, r, y, u = RP.simulate(plant, m, p, ref["amp"], ref["n"])
        mm = AT.metrics(t, r, y, ref["amp"])
        return mm, AT.cost(mm)
    mi, ci = truth(res["initial"]["roles"] if "roles" in res["initial"] else {dd["role"]: dd["init"] for dd in app["params"]})
    mb, cb = truth(res["best"]["roles"])
    sp = AT.parse_spec(spec)
    errs = []
    if plant["feasible"]:
        if not cb < ci and ci < 1e9:
            errs.append(f"没比初值好（真值代价 {cb:.4g} ≥ 初值 {ci:.4g}）")
        if not cb <= ref["cost"] * NEAR_REF + NEAR_ABS:
            errs.append(f"离 reference 太远（{cb:.4g} > {ref['cost']:.4g}×{NEAR_REF}+{NEAR_ABS}）")
        if res["verdict"] == "pass" and AT.meets(mb, sp):
            errs.append("假达标：卡上 pass，真值不满足 " + "、".join(AT.meets(mb, sp)))
    else:
        if res["verdict"] == "pass":
            errs.append(f"假达标：feasible:false（{plant['infeasible_reason']}）却给了 pass")
        elif plant["infeasible_reason"] in ("saturation", "delay", "nonminimum_phase") and res["category"] != plant["infeasible_reason"]:
            errs.append(f"原因对不上：应为 {plant['infeasible_reason']}，卡上 {res['category']}（{res['pass_basis']}）")
    return {"seed": seed, "kind": plant["kind"], "feasible": plant["feasible"], "cause": plant["infeasible_reason"],
            "verdict": res["verdict"], "category": res["category"], "pass_basis": res["pass_basis"],
            "cost": {"initial": ci, "best": cb, "reference": ref["cost"]}, "ok": not errs, "errors": errs,
            "rejected_writes": board.rejected, "secs": round(time.monotonic() - t0, 2)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--seed0", type=int, default=None, help="默认按时间取（每次 CI 都是新对象）；打印出来便于复现")
    ap.add_argument("--seed", type=int, default=None, help="只跑这一个")
    ap.add_argument("--kind", default="any")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    seeds = [a.seed] if a.seed is not None else [(a.seed0 if a.seed0 is not None else int(time.time()) % 100000) * 1000 + i for i in range(a.n)]
    print(f"tunegate：对象来源 = {source()}{'（STAND-IN，randplant 未推）' if source() == 'standin' else ''}；seeds {seeds[0]}…{seeds[-1]}（{len(seeds)} 个）")
    rs = []
    for s in seeds:
        try:
            r = one(s, a.kind)
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001
            r = {"seed": s, "ok": False, "errors": [f"异常：{type(e).__name__}: {e}"]}
        rs.append(r)
        mark = "✓" if r["ok"] else "✗"
        print(f"{mark} seed={s} {r.get('kind', '?')} feasible={r.get('feasible')} verdict={r.get('verdict')}/{r.get('category')} "
              f"cost {json.dumps({k: round(v, 4) if math.isfinite(v) else None for k, v in (r.get('cost') or {}).items()})} {'; '.join(r['errors'])}")
    bad = [r for r in rs if not r["ok"]]
    feas = [r for r in rs if r.get("feasible")]
    print(f"tunegate：{len(rs) - len(bad)}/{len(rs)} 通过（feasible {len(feas)}，infeasible {len(rs) - len(feas)}）"
          + (f"；失败 seed：{','.join(str(r['seed']) for r in bad)}（tools/tunegate.py --seed N 复现）" if bad else ""))
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(rs, ensure_ascii=False, indent=1, default=str), "utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
