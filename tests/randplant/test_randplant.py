#!/usr/bin/env python3
"""随机对象生成器冒烟测试（make test）。只验生成器本身，不做整定/达标判定（那是后端的门禁）：
  1. 同一 seed 两次生成逐字节相同；不同 seed 不同
  2. 生成的应用在 host-sim 编得过，并且通用链路（0x7B 阶跃、PARAM_SET、param_reject、bit17、急停中止）全部合规
     —— 直接复用 tools/test_step_result.py 的整套检查，应用里没有一行手写链路代码
  3. 改可调参数 kp（×0.5 / ×1.5）→ 板上 step_result 指标可测地变化
种子：RANDPLANT_SEEDS="3 7"（默认）。失败时打印 seed 和 plant.json 摘要。
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import randplant  # noqa: E402

HOME = ROOT / "build" / "randplant-smoke"
os.environ["DZBENCH_HOME"] = str(HOME)
import test_step_result as tsr  # noqa: E402


def files(d: pathlib.Path) -> dict:
    return {p.name: p.read_bytes() for p in sorted(d.iterdir()) if p.is_file()}


def metrics(exe, schema, kp_idx, kp, target, dur=2000):
    _, fr = tsr.run(exe, [f"300 param {kp_idx} {kp}", f"1000 step 0 1 {target} {dur}", f"{1000 + dur + 300} end"])
    r = [r for _, r in tsr.results(fr)]
    return r[0] if r else None


def check_truth(p: dict) -> str:
    """接口约定：link.step 只有物理上限；spec.txt 一句话；plant.json 有采样周期、feasible + 原因类别、reference、items。"""
    y = randplant.app_yaml(p)
    if "abs_tol" in y or "range:" in y.replace("sensor_range:", ""):
        return "link.step 不许写 range / abs_tol"
    if not (p["spec_text"].startswith("阶跃幅度") and "稳态误差不超过" in p["spec_text"]):
        return "spec_text 不是题面式一句话"
    if p["feasible"] == bool(p["reason_category"]) or (not p["feasible"] and not p["reason"]):
        return "feasible / reason_category 不一致"
    if not p["items"] or any(not {"name", "clause", "target", "verdict_expected"} <= set(it) for it in p["items"]):
        return "items 缺字段"
    if p["feasible"]:
        b = p["reference"]["best"]
        vals = {"稳态误差": b["ss_err"], "超调量": b["overshoot_pct"], "调节时间": b["settle_s"]}
        if any(vals[it["name"]] > it["target"]["value"] for it in p["items"]):
            return "feasible 但 reference 自己都不满足 spec"
    if not 0 < p["dt_s"] <= 0.01 or "P" not in p["roles"]:
        return "采样周期 / 角色不对"
    return ""


def main() -> int:
    seeds = [int(s) for s in os.environ.get("RANDPLANT_SEEDS", "3 5 7 10 20").split()]
    fail = 0
    t0 = time.time()
    shutil.rmtree(HOME, ignore_errors=True)
    for seed in seeds:
        p = randplant.gen(seed)
        tag = f"seed={seed} order={p['order']} unit={p['unit']} integ={p['integrator']} gain={p['gain']} tau={p['tau_s']} " \
              f"delay={p['delay_s']} sat={p['sat']} dz={p['deadzone']} noise={p['noise_std']} dt={p['dt_s']} init={p['init']}"
        bad = check_truth(p)
        if bad:
            print(f"✗ [randplant] plant.json 真值不全：{bad}：{tag}"); fail += 1; continue
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            randplant.write(p, pathlib.Path(a)); randplant.write(randplant.gen(seed), pathlib.Path(b))
            same = files(pathlib.Path(a)) == files(pathlib.Path(b))
            other = randplant.gen(seed + 1000)
        if not same or other["ss"] == p["ss"]:
            print(f"✗ [randplant] 不可复现或不同 seed 撞车：{tag}"); fail += 1; continue
        out = HOME / "projects" / p["name"]
        randplant.write(p, out)
        target = round(0.25 * p["sensor_range"], 4)
        tsr.APPS[p["name"]] = {"pre": [], "target": target, "dur": 2000}
        nf, n, summ = tsr.test_app(p["name"])
        if nf:
            print(f"✗ [randplant] 通用链路检查失败 {nf}/{n}：{tag}"); fail += 1; continue
        exe = tsr.ROOT / "build/host-sim" / p["name"] / "step_run"
        schema = json.loads((tsr.ROOT / "build/host-sim" / p["name"] / "linkgen/link_schema.json").read_text())
        pn = p["roles"]["P"]                                   # 比例参数的名字是随机的，角色只在 plant.json 里
        ik = [q["name"] for q in schema["params"]].index(pn)
        kp, q = p["init"][pn], schema["params"][ik]
        d = min(0.5 * kp, 0.9 * q["max_delta"])               # ±50%，但不越过声明的 max_delta / 量程（否则板子按规矩拒绝）
        lo, hi = metrics(exe, schema, ik, kp - d, target), metrics(exe, schema, ik, min(q["max"], kp + d), target)
        if lo and hi and lo["params_hash"] == hi["params_hash"]:
            print(f"✗ [randplant] kp 写入没生效（params_hash 相同）：{tag}"); fail += 1; continue
        keys = ("overshoot_pct", "ss_err_pct", "peak_abs_err", "rise_ms", "settle_ms")
        diff = lo and hi and any(lo[k] != hi[k] and not (lo[k] is not None and hi[k] is not None and abs(lo[k] - hi[k]) < 1e-3) for k in keys)
        if not diff:
            print(f"✗ [randplant] kp ×0.5 / ×1.5 指标没变：{tag}\n   lo={lo}\n   hi={hi}"); fail += 1; continue
        _, frm = tsr.run(exe, [f"1000 step 0 9 {round(1.2 * p['max_step'], 4)} 1000", "1500 end"])   # 超物理上限 max_step → 板子拒绝
        st = [x["status"] for _, x in tsr.acks(frm)]
        if st != ["bad_arg"]:
            print(f"✗ [randplant] 超 max_step 的阶跃应回 status 1（bad_arg）：{st}：{tag}"); fail += 1; continue
        print(f"✓ [randplant] {p['name']} {p['unit']} 阶{p['order']}：链路 {n} 项全过；kp−Δ os={lo['overshoot_pct']:.2f} ss={lo['ss_err_pct']:.2f} "
              f"/ kp+Δ os={hi['overshoot_pct']:.2f} ss={hi['ss_err_pct']:.2f}（feasible={p['feasible']}，仅供评分）")
    print(f"{'✗' if fail else '✓'} randplant 冒烟：{len(seeds)} 个 seed，失败 {fail}，{time.time() - t0:.1f} s")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
