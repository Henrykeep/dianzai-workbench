#!/usr/bin/env python3
"""随机被控对象生成器（host-sim 仿真板，通用链路）。

    python tools/randplant.py --seed N [--order 1-3] [--kind pos|vel|temp|any] --out <dir> [--build] [--run]

<dir> 里输出：
  app.yaml   —— 应用声明（link.telemetry sp/y/u、link.params kp/ki/kd/u_max、link.step），固件全部由 tools/gen_link.py 生成链路
  link.yaml  —— 同一份 link: 段的副本（给只读链路的工具）
  app_main.c —— 通用 PID 回路 + link_app.h（0x7B 阶跃 / PARAM_SET / param_reject 都来自通用库，零手写）
  sim_setup.c—— 被控对象（离散状态空间 + Padé 纯滞后 + 饱和 + 死区 + 噪声），只在 host-sim 编译
  plant.json —— 真值（传函、滞后、饱和、死区、噪声、feasible + reason）。只给评分用，被测方不许读
  build/     —— --build 时：仿真板 sim:randplant-<seed> 的可执行文件（也在仓库 build/host-sim/randplant-<seed>/）

随机系统用 python-control 的 control.rss()（不手写），滞后用 control.pade，所有随机数都来自 numpy.random.default_rng(seed)。
同一 seed + 同一参数 → 逐字节相同的输出。本工具只生成被控对象；辨识/整定/判达标是后端的门禁，不在这里。
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import shutil
import subprocess
import sys

import numpy as np

try:
    import control
except ImportError:  # pragma: no cover
    sys.exit("缺 python-control：pip install -r app/sidecar/requirements.txt")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import plantmodel  # noqa: E402  共享对象模型（plant: 声明也用它）
DT = 0.001                     # 控制/仿真步长（s），与 app_main.c CTRL_PERIOD_US 一致
UNITS = {"pos": ["deg", "mm"], "vel": ["rpm"], "temp": ["°C"], "any": ["deg", "mm", "°C", "rpm", "V"]}
KIND_OF_UNIT = {"deg": "pos", "mm": "pos", "rpm": "vel", "°C": "temp", "V": "vel"}


def _r(x: float, n: int = 6) -> float:
    return float(f"{x:.{n}g}")


def gen(seed: int, order: str = "1-3", kind: str = "any") -> dict:
    rng = np.random.default_rng(seed)
    lo, hi = (int(v) for v in (order.split("-") + [order])[:2])
    n = int(rng.integers(lo, hi + 1))
    unit = str(rng.choice(UNITS[kind]))
    k_eff = KIND_OF_UNIT[unit] if kind == "any" else kind
    integrator = bool(k_eff == "pos" and rng.random() < 0.5)

    # 随机稳定系统：control.rss 的种子来自 numpy 全局状态 → 用 rng 派生一个整数播种（仍由 seed 唯一决定）
    np.random.seed(int(rng.integers(0, 2**31 - 1)))
    while True:
        sys_c = control.rss(n, 1, 1, strictly_proper=True)
        poles = np.asarray(control.poles(sys_c))
        if np.all(poles.real < -1e-3) and abs(float(control.dcgain(sys_c))) > 1e-6:
            break
    # 时间常数缩放到 [0.02, 2] s 的最慢极点
    slow = float(np.min(-poles.real))
    tau = float(np.exp(rng.uniform(np.log(0.02), np.log(2.0))))
    a = slow * tau                                        # s → s/a 让最慢极点 = 1/tau
    # 时间缩放：极点/零点除以 a → 最慢极点 = 1/tau（形状保持，增益下面重定）
    zs, ps, kz = _zpk(sys_c)
    ps = ps / a; zs = zs / a
    g = _from_zpk(zs, ps)
    gain = float(np.exp(rng.uniform(np.log(0.2), np.log(50.0))))   # 恒正：通用 PID（firmware/algo/pid）不收负增益；方向由接线/声明解决
    g = g * (gain / float(control.dcgain(g)))
    if integrator:
        g = g * control.tf([1.0], [1.0, 0.0]) * (1.0 / max(tau, 0.05))
    delay = float(rng.choice([0.0, rng.uniform(0.002, 0.3 * tau + 0.002)])) if rng.random() < 0.6 else 0.0
    delay = round(delay, 4)
    sat = _r(float(rng.uniform(0.5, 1.0)))               # 执行器饱和（归一化输出）
    dz = _r(float(rng.choice([0.0, rng.uniform(0.0, 0.12)])))   # 执行器死区（归一化）
    # 量程：开环在 u=sat 下的稳态（积分对象取 1 s 行程），取整
    yspan = abs(gain) * sat if not integrator else abs(gain) * sat / max(tau, 0.05) * 1.0
    rng_span = _r(max(1e-3, 2.0 * yspan), 3)
    noise = _r(float(rng.choice([0.0, rng.uniform(0, 0.005)])) * rng_span, 3)
    abs_tol = _r(max(0.01 * rng_span, 3 * noise, 1e-4), 3)

    gd = g
    if delay > 0:
        pn, pd = control.pade(delay, 2)
        gd = g * control.tf(pn, pd)
    sysd = control.c2d(control.ss(gd), DT, method="zoh")
    A, B, C, D = (np.asarray(m, dtype=float) for m in (sysd.A, sysd.B, sysd.C, sysd.D))

    # 可调参数范围：按对象增益/时间常数定量级（不同题目量纲不同，范围随对象走）
    k0 = 1.0 / (abs(gain) if not integrator else abs(gain) / max(tau, 0.05))
    ranges = {"kp": (0.0, _r(20 * k0, 3)), "ki": (0.0, _r(20 * k0 / max(tau, 0.02), 3)), "kd": (0.0, _r(2 * k0 * tau, 3))}
    init = {k: _r(float(rng.uniform(lo_, hi_)), 4) for k, (lo_, hi_) in ranges.items()}
    feas, reason = _feasible(g, delay, sat, dz, ranges, rng_span, abs_tol)
    return {
        "seed": seed, "name": f"randplant-{seed}", "kind": k_eff, "unit": unit, "order": n, "integrator": integrator,
        "tf": {"num": [_r(float(c)) for c in np.ravel(control.tfdata(g)[0][0][0])],
               "den": [_r(float(c)) for c in np.ravel(control.tfdata(g)[1][0][0])]},
        "gain": _r(gain), "tau_s": _r(tau), "delay_s": delay, "pade_order": 2 if delay > 0 else 0,
        "sat": sat, "deadzone": dz, "noise_std": noise, "range": rng_span, "abs_tol": abs_tol,
        "ranges": {k: list(v) for k, v in ranges.items()}, "init": init,
        "dt_s": DT, "ss": {"A": A.tolist(), "B": B.ravel().tolist(), "C": C.ravel().tolist(), "D": float(D.ravel()[0])},
        "feasible": feas, "reason": reason,
    }


def _zpk(s):
    tf = control.ss2tf(s)
    return np.asarray(control.zeros(tf)), np.asarray(control.poles(tf)), 1.0


def _from_zpk(z, p):
    num = np.real(np.poly(z)) if len(z) else np.array([1.0])
    den = np.real(np.poly(p))
    return control.tf(num, den)


def _feasible(g, delay, sat, dz, ranges, span, tol):
    """仅评分用：线性近似（忽略噪声；死区/饱和只做量级判断），在参数范围的粗网格上找一组闭环稳定且
    10 s 内进入 ±tol 的 PID。找不到 → infeasible + 原因。不是整定算法，也不进任何门禁。"""
    if dz >= 0.5 * sat:
        return False, f"死区 {dz} ≥ 饱和 {sat} 的一半，可用输出太窄"
    gd = g
    if delay > 0:
        pn, pd = control.pade(delay, 2); gd = g * control.tf(pn, pd)
    s = control.tf("s")
    sp = 0.25 * span
    def grid(lo, hi, m):                                   # 对数网格（含号），跨 3 个数量级
        e = hi if abs(hi) > abs(lo) else lo
        return np.array([0.0]) if e == 0 else e * np.geomspace(1e-3, 1.0, m)
    t = np.linspace(0, 10, 2001)
    for kp in grid(*ranges["kp"], 10):
        for ki in np.r_[0.0, grid(*ranges["ki"], 6)]:
            for kd in (0.0,):
                c = kp + ki / s + kd * s / (0.01 * s + 1)
                cl = control.feedback(c * gd, 1)
                if np.any(np.real(control.poles(cl)) >= 0):
                    continue
                _, y = control.step_response(cl * sp, t)
                _, u = control.step_response(control.feedback(c, gd) * sp, t)
                if np.max(np.abs(u[200:])) > sat * 1.5:
                    continue
                if np.all(np.abs(y[-200:] - sp) <= tol):
                    return True, ""
    return False, "参数范围内的粗网格找不到闭环稳定且 10 s 内进 ±abs_tol 的 PID（线性近似）"


def app_yaml(p: dict) -> str:
    u = p["unit"]; r = p["ranges"]; i = p["init"]
    md = lambda k: _r((r[k][1] - r[k][0]) * 0.25, 3)   # 单次最多改量程的 1/4
    return f"""# 由 tools/randplant.py --seed {p['seed']} 生成：随机被控对象（只在 host-sim 上跑）。不要手改，重新生成。
name: {p['name']}
version: 1.0.0
description: 随机对象 seed={p['seed']}（阶 {p['order']}，{p['kind']}，单位 {u}）
requires:
  uart: [LINK]
  timer: [CTRL]
link:
  telemetry:
    id: 2
    period_ms: 10
    fields:
      - {{ name: t_ms, type: uint32, unit: ms }}
      - {{ name: sp, type: float, unit: "{u}", ref_for: y, hold: latched }}
      - {{ name: y, type: float, unit: "{u}" }}
      - {{ name: u, type: float }}
      - {{ name: run, type: uint8, enum: [STOPPED, RUNNING, ESTOP], pin: 状态 }}
  step:
    - {{ sp: 0, y: y, u: u, u_max: u_max, range: {p['range']}, abs_tol: {p['abs_tol']} }}
  params:
    - {{ name: kp, type: float, default: {i['kp']}, min: {r['kp'][0]}, max: {r['kp'][1]}, max_delta: {md('kp')} }}
    - {{ name: ki, type: float, default: {i['ki']}, min: {r['ki'][0]}, max: {r['ki'][1]}, max_delta: {md('ki')} }}
    - {{ name: kd, type: float, default: {i['kd']}, min: {r['kd'][0]}, max: {r['kd'][1]}, max_delta: {md('kd')} }}
    - {{ name: u_max, type: float, default: 1.0, min: 0.1, max: 1 }}
"""


def sim_c(p: dict) -> str:
    """对象 C 代码：与 plant: 声明共用 tools/plantmodel.py（滞后已用 Padé 折进状态空间）。"""
    return plantmodel.sim_c(p["ss"], dt=DT, sat=(-float(p["sat"]), float(p["sat"])), deadzone=float(p["deadzone"]),
                            noise_std=float(p["noise_std"]), seed=int(p["seed"]), tag=f"tools/randplant.py --seed {p['seed']}")


APP_MAIN = plantmodel.generic_app(int(round(DT * 1e6)))


def write(p: dict, out: pathlib.Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    y = app_yaml(p)
    (out / "app.yaml").write_text(y, encoding="utf-8")
    (out / "link.yaml").write_text(y[y.index("link:"):], encoding="utf-8")
    (out / "app_main.c").write_text(APP_MAIN, encoding="utf-8")
    (out / "sim_setup.c").write_text(sim_c(p), encoding="utf-8")
    (out / "plant.json").write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")


def build(p: dict, out: pathlib.Path) -> pathlib.Path:
    """在仓库 build/host-sim/<name>/ 编出仿真板（侧车按 sim:<name> 找它），再拷一份到 <out>/build/。"""
    name = p["name"]
    subprocess.run(["make", "-s", "-C", str(ROOT), "BOARD=host-sim", f"APP={name}", f"APP_DIR={out.resolve()}"], check=True,
                   stdout=subprocess.DEVNULL)
    exe = ".exe" if sys.platform == "win32" else ""
    elf = ROOT / "build" / "host-sim" / name / f"{name}.elf{exe}"
    (out / "build").mkdir(exist_ok=True)
    shutil.copy2(elf, out / "build" / elf.name)
    return elf


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--order", default="1-3")
    ap.add_argument("--kind", default="any", choices=list(UNITS))
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--build", action="store_true", help="编出仿真板 sim:randplant-<seed>")
    ap.add_argument("--run", action="store_true", help="编完直接启动仿真板（前台，Ctrl+C 结束）")
    a = ap.parse_args(argv)
    p = gen(a.seed, a.order, a.kind)
    write(p, a.out)
    print(f"{p['name']}: order={p['order']} unit={p['unit']} integrator={p['integrator']} feasible={p['feasible']} → {a.out}")
    if a.build or a.run:
        elf = build(p, a.out)
        print(f"仿真板 sim:{p['name']} → {elf}")
        if a.run:
            return subprocess.call([str(elf)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
