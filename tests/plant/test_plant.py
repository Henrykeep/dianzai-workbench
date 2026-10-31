#!/usr/bin/env python3
"""#89 app.yaml plant: 声明 → host-sim 通用对象板（make test）。没有任何题目专用对象代码：
  1. schema 正反例（tools/plantmodel.py validate）
  2. 生成的对象 C 与声明一致：对同一串随机 u，C（float）与 python-control 离散仿真逐点对拍（无噪声；含纯滞后/饱和/死区）
  3. 闭环：只写 plant: 的新工程 → plantmodel scaffold（通用 PID + 通用链路）→ make BOARD=host-sim 编过 →
     tests/step/step_run 驱动：PARAM_SET 写 PI → 给设定值 → y 收敛到设定值附近
     用例：seed 随机声明若干、热对象（一阶+滞后、单边饱和、环境值）、不稳定一阶、欠阻尼二阶、积分对象
种子：PLANT_SEEDS="11 12 13"（默认）。
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
HOME = ROOT / "build" / "plant-test"
os.environ["DZBENCH_HOME"] = str(HOME)
import plantmodel as pm  # noqa: E402
import test_step_result as tsr  # noqa: E402
import control  # noqa: E402

fail = 0


def ok(cond: bool, msg: str) -> None:
    global fail
    print(("✓ " if cond else "✗ ") + msg)
    fail += not cond


# ------------------------------------------------------------------ 1 schema
GOOD = {"order": 1, "gain": 2.0, "tau_s": [0.5], "unit": "kPa", "estimate": "coarse"}
BAD = {
    "缺 estimate": {k: v for k, v in GOOD.items() if k != "estimate"},
    "estimate 取值": {**GOOD, "estimate": "guess"},
    "阶次不符": {**GOOD, "order": 2},
    "tf 与 gain 同给": {**GOOD, "tf": {"num": [1], "den": [1, 1]}},
    "饱和 min≥max": {**GOOD, "saturation": {"min": 1, "max": 0}},
    "死区≥饱和": {**GOOD, "saturation": 1, "deadzone": 1.5},
    "滞后太长": {**GOOD, "delay_s": 9.5, "sample_s": 0.001},
    "未知字段": {**GOOD, "kp": 1},
    "zeta 无 wn": {**GOOD, "order": 3, "zeta": 0.3},
    "阶次 4": {**GOOD, "order": 4},
}


def schema_tests() -> None:
    ok(pm.validate(GOOD) == [], "schema：合法一阶声明通过")
    ok(pm.validate({"order": 2, "tf": {"num": [3], "den": [1, 2, 3]}, "unit": "%RH", "estimate": "identified"}) == [],
       "schema：tf 形式（辨识回写）通过")
    for why, d in BAD.items():
        e = pm.validate(d)
        ok(bool(e), f"schema 拒绝：{why}（{e[0] if e else '没报错'}）")


# ------------------------------------------------------------------ 2 C ↔ python-control 对拍
HARNESS = r"""#include <stdio.h>
float sim_plant_step(float u);
int main(void){ float u; while (scanf("%f",&u)==1) printf("%.9g\n",(double)sim_plant_step(u)); return 0; }
"""


def ref_trace(d: dict, us: np.ndarray) -> np.ndarray:
    dt = float(d.get("sample_s", 0.001))
    ss = pm.discretize(pm.continuous(d), dt)
    A, B, C, D = (np.asarray(ss[k], dtype=float) for k in "ABCD")
    lo, hi = pm.sat_limits(d); dz = float(d.get("deadzone", 0)); n = int(round(float(d.get("delay_s", 0)) / dt))
    buf = [0.0] * n; x = np.zeros(len(B)); out = []
    for i, u in enumerate(us):
        u = min(max(float(u), lo), hi)
        u = 0.0 if abs(u) <= dz else (u - dz if u > 0 else u + dz)
        if n:
            buf.append(u); u = buf.pop(0)
        out.append(float(d.get("y0", 0)) + float(C @ x) + float(D) * u)
        x = A @ x + B * u
    return np.array(out)


def trace_test(name: str, d: dict, rng) -> None:
    d = {**d, "noise_std": 0.0}
    with tempfile.TemporaryDirectory() as t:
        t = pathlib.Path(t)
        (t / "p.c").write_text(pm.gen_c(d)); (t / "h.c").write_text(HARNESS)
        subprocess.run(["cc", "-std=c11", "-O1", "-Wall", "-Werror", str(t / "p.c"), str(t / "h.c"), "-lm", "-o", str(t / "x")], check=True)
        lo, hi = pm.sat_limits(d)
        us = np.repeat(rng.uniform(lo - 0.2 * (hi - lo), hi + 0.2 * (hi - lo), 40), 50)
        y = np.array([float(v) for v in subprocess.run([str(t / "x")], input="\n".join(f"{u:.9g}" for u in us), capture_output=True,
                                                       text=True, check=True).stdout.split()])
    r = ref_trace(d, us)
    ylo, yhi = pm.y_range(d)                          # #103：C 对象把 y 钳在量程内；只在参考轨迹还没出量程的那段对拍
    out = np.nonzero((r < ylo) | (r > yhi))[0]
    n = int(out[0]) if out.size else len(r)
    ok(bool(np.all((y >= ylo - 1e-3 * (yhi - ylo)) & (y <= yhi + 1e-3 * (yhi - ylo)))), f"{name}：C 对象输出始终在量程 [{ylo:.4g}, {yhi:.4g}] 内")
    if n < 10:
        return
    r, y = r[:n], y[:n]
    scale = max(1e-6, float(np.max(np.abs(r - float(d.get("y0", 0))))))
    err = float(np.max(np.abs(y - r))) / scale
    ok(err < 2e-3, f"对拍 {name}：C 对象 vs python-control 离散仿真 {n} 拍（量程内），最大相对误差 {err:.2e}")


# ------------------------------------------------------------------ 3 闭环
def closed_loop(name: str, d: dict, kp: float, ki: float, target: float, run_ms: int, tol: float) -> None:
    proj = HOME / "projects" / name
    shutil.rmtree(proj, ignore_errors=True)
    proj.mkdir(parents=True)
    src = proj.parent / f"{name}.app.yaml"
    import yaml
    src.write_text(f"name: {name}\nversion: 0.1.0\ndescription: 声明对象闭环测试\n"
                   + yaml.safe_dump({"plant": d}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    pm.scaffold(src, proj)
    exe, schema = tsr.build(name)
    gen = tsr.ROOT / "build/host-sim" / name / "plantgen/plant_sim.c"
    ok(gen.exists(), f"{name}：通用对象板由 plant: 生成 {gen.relative_to(ROOT)}")
    names = [q["name"] for q in schema["params"]]
    script, t = [], 100
    for k, v in (("kp", kp), ("ki", ki)):                 # 按声明的 max_delta 分步写（越过会被板子按规矩 param_reject）
        q = schema["params"][names.index(k)]
        cur = float(q.get("default", 0))
        while abs(v - cur) > 1e-12:
            cur = cur + max(-0.9 * q["max_delta"], min(0.9 * q["max_delta"], v - cur))
            script.append(f"{t} param {names.index(k)} {cur:.9g}"); t += 20
    script += [f"{max(t, 500)} sp {target}", f"{max(t, 500) + run_ms} end"]
    run_ms += max(t, 500) - 500
    _, fr = tsr.run(exe, script)
    tel = tsr.telem(schema, fr)
    tail = [t["y"] for t in tel if t["t_ms"] >= run_ms - 0.15 * (run_ms - 500)]
    y = float(np.mean(tail)) if tail else float("nan")
    ok(abs(y - target) <= tol,
       f"{name}：闭环 kp={kp:g} ki={ki:g} sp={target:g} {d['unit']} → 末段 y={y:.4g}（容差 ±{tol:g}，{len(tel)} 帧）")


def random_decl(seed: int) -> dict:
    rng = np.random.default_rng(seed)
    n = int(rng.integers(1, 4))
    taus = sorted((float(f"{x:.3g}") for x in rng.uniform(0.02, 0.3, n)), reverse=True)
    return {"order": n, "gain": float(f"{rng.uniform(0.5, 5):.3g}"), "tau_s": taus,
            "delay_s": float(f"{rng.choice([0.0, 0.1 * taus[0]]):.3g}"), "saturation": 1.0,
            "deadzone": float(f"{rng.uniform(0, 0.03):.3g}"), "noise_std": float(f"{rng.uniform(0, 0.002):.3g}"),
            "unit": str(rng.choice(["mm", "kPa", "%RH", "rpm", "A", "lux"])), "sample_s": 0.001, "seed": seed, "estimate": "coarse"}


def pi_for(d: dict) -> tuple[float, float]:
    """测试用的保守 PI（不是整定算法）：python-control 在小网格上挑一个闭环稳定、每个闭环极点阻尼比 ≥ 0.35、带宽最大的。"""
    g = pm.continuous(d)
    if d.get("delay_s"):
        pn, pd = control.pade(float(d["delay_s"]), 3); g = g * control.tf(pn, pd)
    s = control.tf("s")
    rng, _ = pm.param_ranges(d)
    op = np.asarray(control.poles(g)); op = op[(np.abs(op) > 1e-9) & (op.real < 0)]
    thr = min(0.35, 0.8 * float(np.min(-op.real / np.abs(op)))) if op.size else 0.35   # PI 改不了对象自身的弱阻尼极点
    best = None
    for kp in rng["kp"][1] * np.geomspace(1e-3, 1, 25):
        for ki in [0.0, *(rng["ki"][1] * np.geomspace(1e-3, 1, 15))]:
            if ki == 0 and not d.get("integrator"):   # 自带积分的对象 P 就无静差
                continue
            try:
                ps = np.asarray(control.poles(control.feedback(((kp + ki / s) if ki else control.tf([kp], [1.0])) * g, 1)))
            except np.linalg.LinAlgError:
                continue
            if np.any(ps.real >= -1e-6):
                continue
            if np.min(-ps.real / np.maximum(np.abs(ps), 1e-12)) < thr:   # 每个闭环极点阻尼 ≥ thr
                continue
            slow = float(np.min(-ps.real))
            if best is None or slow > best[0]:
                best = (slow, float(f"{kp:.4g}"), float(f"{ki:.4g}"))
    assert best, f"测试对象没有可用 PI：{d}"
    return best[1], best[2], 6.0 / best[0]                # 第三项：按最慢闭环极点估的收敛时间（s）


def main() -> int:
    t0 = time.time()
    shutil.rmtree(HOME, ignore_errors=True)
    schema_tests()
    rng = np.random.default_rng(89)
    seeds = [int(s) for s in os.environ.get("PLANT_SEEDS", "11 12 13").split()]
    thermal = {"order": 1, "gain": 0.6, "tau_s": [8.0], "delay_s": 0.8, "saturation": {"min": 0, "max": 100}, "y0": 25.0,
               "noise_std": 0.05, "unit": "°C", "u_unit": "%", "sample_s": 0.01, "estimate": "coarse", "basis": "一阶加纯滞后粗估"}
    unstable = {"order": 1, "gain": -2.0, "tau_s": [-0.5], "saturation": 1.0, "unit": "deg", "sample_s": 0.001, "estimate": "coarse"}
    second = {"order": 2, "gain": 1.5, "zeta": 0.15, "wn_rad_s": 12.0, "saturation": 1.0, "unit": "mm", "sample_s": 0.001, "estimate": "identified"}
    integ = {"order": 2, "gain": 3.0, "tau_s": [0.05], "integrator": True, "saturation": 1.0, "deadzone": 0.02,
             "unit": "deg", "sample_s": 0.001, "estimate": "coarse"}
    cases = [(f"plant-rand-{s}", random_decl(s)) for s in seeds] + \
            [("plant-thermal", thermal), ("plant-unstable", unstable), ("plant-2nd", second), ("plant-integ", integ)]
    for name, d in cases:
        ok(pm.validate(d) == [], f"{name}：声明合法 {pm.validate(d)}")
        trace_test(name, d, rng)
    for name, d in cases:
        kp, ki, settle = pi_for(d)
        lo, hi = pm.sat_limits(d)
        y0 = float(d.get("y0", 0))
        if d.get("integrator"):
            target = 10.0
        else:
            dc, _ = pm.static_gain(pm.continuous(d))
            target = y0 + 0.4 * dc * (hi if dc > 0 else lo)
        run_ms = int(500 + 1000 * min(90.0, max(2.0, 1.5 * settle + float(d.get("delay_s", 0)))))
        tol = max(0.03 * abs(target - y0), 4 * float(d.get("noise_std", 0)))
        try:
            closed_loop(name, d, kp, ki, round(target, 4), run_ms, tol)
        except Exception as e:  # noqa: BLE001
            ok(False, f"{name}：构建/运行失败 {e}")
    print(f"{'✗' if fail else '✓'} plant: 通用对象板：失败 {fail}，{time.time() - t0:.1f} s")
    shutil.rmtree(HOME, ignore_errors=True)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
