#!/usr/bin/env python3
"""#124/#125 randplant 可行性标签的回归（make test）。对 FEAS_SEEDS（默认 4001–4040 + 3001–3012）每个对象：
  A. 独立交叉检查：用判卷侧的整定器（dzbench.tuning.autotune.design，不同的 PID 实现 + 判卷口径 metrics/meets）
     在同一对象上另搜一组参数；只要它满足题面全部条目，randplant 就不许标 feasible:false（可以是 true 或 "unknown"）。
  B. feasible:true 时 plant.json 里的 witness/reference 在固件同一模型上确实满足题面（randplant 自证）。
  C. feasible 不是 true 时 reason_category 与这里独立写的结构分类器一致（饱和 / 滞后 / 右半平面零点 / 无积分稳态误差）。
"""
from __future__ import annotations

import os
import pathlib
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "app" / "sidecar")]
import randplant  # noqa: E402

SEEDS = [int(s) for s in os.environ.get("FEAS_SEEDS", " ".join(map(str, [*range(4001, 4041), *range(3001, 3013)]))).split()]


def model_class(p: dict) -> set[str]:
    """独立的结构分类：返回可以接受的类别集合（结构原因明确时只有一个）。"""
    amp = p["reference"]["step_amp"]
    ss_t = next(it["target"]["value"] for it in p["items"] if it["name"] == "稳态误差")
    if not p["integrator"]:
        y_max = p["gain"] * max(0.0, p["sat"] - p["deadzone"])     # 满输出时的稳态输出（直流增益恒正）
        if y_max < abs(amp) - ss_t:
            return {"saturation"}
    tau, delay = p["tau_s"], p["delay_s"]
    zs = [z for z in np.roots(p["tf"]["num"]) if z.real > 0 and abs(z) * tau < 1e6] if len(p["tf"]["num"]) > 1 else []
    tz = 1.0 / min(z.real for z in zs) if zs else 0.0
    if delay >= tau:
        return {"delay_too_large"}
    if tz >= max(0.5 * tau, delay):
        return {"unstable_zero"}
    ok = {"spec_too_tight"}
    if "I" not in p["roles"] and not p["integrator"]:
        ok.add("steady_state_error")
    if tz >= max(0.1 * tau, delay):
        ok.add("unstable_zero")
    if delay >= 0.5 * tau:
        ok.add("delay_too_large")
    return ok


def one(seed: int) -> list[str]:
    import tunegate_plant as TP
    from dzbench.tuning import autotune as AT
    p = randplant.gen(seed)
    d = TP.make(seed)
    errs = []
    if p["feasible"] not in (True, False, "unknown"):
        errs.append(f"feasible 取值不对：{p['feasible']!r}")
    sp = AT.parse_spec(d["spec"])
    indep_ok = not AT.meets(d["plant"]["reference"]["metrics"], sp)
    if indep_ok and p["feasible"] is False:
        errs.append(f"独立搜索满足题面（{d['plant']['reference']['params_roles']}），randplant 却标 feasible:false（{p['reason_category']}）")
    if p["feasible"] is True:
        b, tg = p["reference"]["best"], {it["name"]: it["target"]["value"] for it in p["items"]}
        vals = {"稳态误差": b["ss_err"], "超调量": b["overshoot_pct"], "调节时间": b["settle_s"]}
        if any(vals[k] > v * (1 + 1e-6) for k, v in tg.items()):
            errs.append(f"feasible:true 但参考参数不满足题面：{vals} vs {tg}")
        if p["reason_category"]:
            errs.append("feasible:true 还带原因类别")
        if not p["feasibility"]["witness"]:
            errs.append("feasible:true 没给 witness")
    else:
        want = model_class(p)
        if p["reason_category"] not in want:
            errs.append(f"原因类别 {p['reason_category']} ≠ 结构分类 {sorted(want)}")
    return [f"seed={seed}: {e}" for e in errs], p["feasible"]


def main() -> int:
    with ProcessPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as ex:
        res = list(ex.map(one, SEEDS))
    import feascheck
    bad = [e for r, _ in res for e in r]
    st = feascheck.summarize(dict(zip(SEEDS, (f for _, f in res))))
    if st["ratio"] > feascheck.MAX_UNKNOWN:
        bad.append(f"unknown 比例 {st['ratio']:.1%} > {feascheck.MAX_UNKNOWN:.0%}（{st['unknown_seeds']}）")
    for e in bad:
        print("✗ [randplant feasible]", e)
    print(f"randplant feasible：{len(SEEDS) - sum(1 for r, _ in res if r)}/{len(SEEDS)} 个种子标签自洽；unknown {st['unknown']}/{st['n']}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
