#!/usr/bin/env python3
"""#78 随机对象门禁：没见过的被控对象上，后端通用整定（dzbench.tuning.autotune）必须
  - feasible 对象：比初值好，并接近 plant.json reference（同幅度、同时长、无噪声的真值上比代价）；给了 pass 但真值不达标 = 假达标 → 红；
  - feasible:false 对象：verdict 必须是 fail/unknown，原因类别对得上（saturation / delay / nonminimum_phase）；给 pass = 红。
失败一律打印 seed，`tunegate.py --seed N` 单独复现。

对象来源（默认）：tools/randplant.py（嵌入式开发-2，与 plant: 共用 tools/plantmodel.py），经 tools/tunegate_plant.py 转成整定输入 + Python 仿真板。
TUNEGATE_SOURCE=standin 只给单元测试显式选用 tools/randplant_standin.py；替身上的结果一律打印「未合入」，退出码非 0，永不算通过。
整定只读 app.yaml / link.yaml / spec.txt；plant.json / 真值只有 tools/tunegate_grade.py 读（check_no_truth_leak 守着）。
可行性三态 True/False/"unknown"：unknown 走 feascheck.judge()，undecided 单独计数不进通过率；标签 false 而复核可达 = truth_label_suspect。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import sys
import tempfile
import time

MAX_UNKNOWN = float(os.environ.get("FEAS_MAX_UNKNOWN", "0.10"))
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app" / "sidecar"))
sys.path.insert(0, str(ROOT / "tools"))



def source() -> str:
    """默认 randplant；只有 TUNEGATE_SOURCE=standin 才用替身（单元测试显式选用）。"""
    return "standin" if os.environ.get("TUNEGATE_SOURCE", "randplant") == "standin" else "randplant"


def one(seed: int, kind: str) -> dict:
    """整定只读 app.yaml / link.yaml / spec.txt；仿真板和判卷都交给 tunegate_grade（唯一读真值的模块）。"""
    import yaml
    import tunegate_grade as G
    from dzbench.tuning import autotune as AT
    if source() == "randplant":
        import tunegate_plant as RP
    else:
        import randplant_standin as RP
    with tempfile.TemporaryDirectory() as d:
        RP.make(seed, kind, d)
        app = yaml.safe_load(open(f"{d}/app.yaml", encoding="utf-8"))
        link = yaml.safe_load(open(f"{d}/link.yaml", encoding="utf-8"))
        spec = open(f"{d}/spec.txt", encoding="utf-8").read()
        board = G.board(d, app, seed, source())
        t0 = time.monotonic()
        res = AT.autotune(board, app, link, spec, seed)
        secs = round(time.monotonic() - t0, 2)
        out = G.grade(d, seed, res, app, spec, source())
    return out | {"rejected_writes": board.rejected, "secs": secs, "amp_reduced": bool(res.get("amp_reduced"))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--seed0", type=int, default=None, help="默认按时间取（每次 CI 都是新对象）；打印出来便于复现")
    ap.add_argument("--seed", type=int, default=None, help="只跑这一个")
    ap.add_argument("--seeds", default=None, help="逗号分隔的固定种子，再加 --n 个按时间取的新种子")
    ap.add_argument("--date-seed", action="store_true", help="再加一个按 UTC 日期取的种子（YYYYMMDD，当天可复现：--seed YYYYMMDD）")
    ap.add_argument("--kind", default="any")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    fixed = [int(x) for x in a.seeds.split(",")] if a.seeds else []
    seeds = [a.seed] if a.seed is not None else fixed +  [(a.seed0 if a.seed0 is not None else int(time.time()) % 100000) * 1000 + i for i in range(a.n)]
    if a.date_seed and a.seed is None:
        ds = int(time.strftime("%Y%m%d", time.gmtime()))
        seeds.append(ds)
        print(f"tunegate：日期种子 {ds}（复现：tools/tunegate.py --seed {ds}）")
    t_start = time.monotonic()
    print(f"tunegate：对象来源 = {source()}{'（STAND-IN，未合入）' if source() == 'standin' else ''}；seeds {seeds[0]}…{seeds[-1]}（{len(seeds)} 个）")
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
    und = [r for r in rs if r.get("bucket") == "undecided"]
    sus = [r for r in rs if r.get("bucket") == "truth_label_suspect"]
    bad = [r for r in rs if not r["ok"]]
    fake = [r for r in rs if r.get("false_pass")]
    feas = [r for r in rs if r.get("feasible") is True]
    infe = [r for r in rs if r.get("feasible") is False]
    unk = [r for r in rs if r.get("feasible") == "unknown"]
    den = len(rs) - len(und)                                        # undecided 不进通过率分母
    good = den - len(bad)
    print(f"tunegate：{good}/{den} 通过（feasible {len(feas)}，infeasible {len(infe)}，unknown {len(unk)}；undecided {len(und)} 不计）"
          + (f"；失败 seed：{','.join(str(r['seed']) for r in bad)}（tools/tunegate.py --seed N 复现）" if bad else ""))
    ratio = len(unk) / len(rs) if rs else 0.0
    print(f"tunegate：feasible=unknown {len(unk)}/{len(rs)}（{ratio:.0%}）" + (f"：seed {','.join(str(r['seed']) for r in unk)}" if unk else ""))
    if ratio > MAX_UNKNOWN:
        print(f"::warning::tunegate unknown 比例 {ratio:.0%} > {MAX_UNKNOWN:.0%}（randplant 标签不确定的太多）")
    print(f"tunegate：truth_label_suspect {len(sus)} 个（标签 false、复核找到达标参数；不算后端假达标）" + (f"：seed {','.join(str(r['seed']) for r in sus)}" if sus else ""))
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(rs, ensure_ascii=False, indent=1, default=str), "utf-8")
    if source() == "standin":
        print("tunegate：未合入——对象来自 STAND-IN（TUNEGATE_SOURCE=standin），结果不算门禁通过")
        return 2
    print(f"tunegate：用时 {time.monotonic() - t_start:.1f} s")
    if bad:
        print(f"::warning::tunegate 通过率 {good}/{den}；未通过 seed {','.join(str(r['seed']) for r in bad)}")
    print(f"tunegate：假达标 {len(fake)} 个（硬门禁，必须 0）" + (f"：seed {','.join(str(r['seed']) for r in fake)}" if fake else "")
          + f"；通过率 {good}/{den}（软指标，未通过只警告）")
    return 1 if fake else 0


if __name__ == "__main__":
    sys.exit(main())
