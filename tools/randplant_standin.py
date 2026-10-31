#!/usr/bin/env python3
"""!!! STAND-IN（临时替身）!!! 嵌入式开发-2 的 tools/randplant.py 推上来之前，给 #78 门禁（tools/tunegate.py）用的本地随机对象。

接口照 randplant 约定：--seed N --kind pos|vel|temp|any --out DIR → app.yaml / link.yaml / spec.txt / plant.json（真值 + reference + feasible）。
区别：没有 build/ 和 sim:randplant-<seed> 固件板；板子是本文件里的 Python SimBoard（同样拒写超 max_delta 的写参）。
randplant 一到就删掉本文件，tunegate 自动改走真的。
核心：python-control rss 随机稳定系统 + pade/整数拍时延 + 饱和 + 死区 + 噪声；随机数全部来自 numpy Generator(seed)。
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app" / "sidecar"))
from dzbench.tuning import autotune as AT  # noqa: E402

STANDIN = True
UNITS = {"pos": ["deg", "mm"], "vel": ["rpm"], "temp": ["°C"], "any": ["deg", "mm", "°C", "rpm", "V", "%RH", "kPa", "A", "zq"]}
NAMES = {"kp": ["kp", "p_gain", "gain_p", "k1", "pos_k"], "ki": ["ki", "i_gain", "k2", "integ"], "kd": ["kd", "d_gain", "k3", "damp"],
         "ff": ["ff", "kff", "feedfwd"], "ulim": ["ulim", "out_max", "lim"]}
CAUSES = ("saturation", "delay", "nonminimum_phase")


def _rss(rng, n):
    """python-control rss 生成随机稳定系统；control 内部用 numpy 全局随机 → 用 Generator 派生的种子固定住。"""
    import control
    np.random.seed(int(rng.integers(2**31)))
    while True:
        s = control.rss(n, 1, 1, strictly_proper=True)
        tf = control.tf(s)
        z = control.zeros(tf)   # 随机零点可能落在右半面：非最小相位只由 cause 注入，原因类别才对得上
        if abs(float(control.dcgain(tf))) > 1e-3 and np.all(np.real(control.poles(tf)) < -1e-3) and np.all(np.real(z) < 0):
            return tf


def make(seed: int, kind: str = "any", out: str | None = None) -> dict:
    import control
    rng = np.random.default_rng(seed)
    if kind == "any":
        kind = str(rng.choice(["pos", "vel", "temp", "any"]))
    n = int(rng.integers(1, 4))
    tf = _rss(rng, n)
    p = control.poles(tf)
    tdom = 1.0 / float(np.min(np.abs(np.real(p))))           # 最慢时间常数
    tscale = {"temp": rng.uniform(20, 200), "vel": rng.uniform(0.05, 1.0), "pos": rng.uniform(0.05, 0.8)}.get(kind, 10 ** rng.uniform(-1.3, 1.5))
    s = control.tf("s")
    a = tdom / tscale
    G = _rescale(tf, a)
    K = float(10 ** rng.uniform(-1, 1.3))
    G = G * (K / float(control.dcgain(G)))
    if kind == "pos":
        G = G * (1 / s) * (1.0 / tscale)                     # 积分对象
    cause = str(rng.choice(CAUSES)) if rng.random() < 0.3 else None
    T = tscale
    L = float(rng.uniform(0, 0.3) * T) if cause != "delay" else float(rng.uniform(2.0, 4.0) * T)
    if cause == "nonminimum_phase":
        z = float(rng.uniform(0.6, 1.5) / T)
        G = G * control.tf([-1 / z, 1], [1])
    dt = float(T / rng.uniform(15, 40))
    rngphys = float(10 ** rng.uniform(0, 3))
    amp_ref = rngphys / 4
    u_max = float(abs(amp_ref / (K if kind != "pos" else 1.0)) * rng.uniform(2.0, 8.0))
    if cause == "saturation":
        u_max = float(abs(amp_ref / (K if kind != "pos" else 1.0)) * rng.uniform(0.05, 0.2) * (1 if kind != "pos" else 1))
    dz = float(u_max * rng.uniform(0, 0.02))
    noise = float(amp_ref * rng.uniform(0, 0.005))
    roles = ["kp"] + [r for r in ("ki", "kd", "ff", "ulim") if rng.random() < {"ki": 0.8, "kd": 0.5, "ff": 0.25, "ulim": 0.2}[r]]
    kscale = 1.0 / abs(float(control.dcgain(G))) if kind != "pos" else tscale / max(T, 1e-9)
    kscale = kscale if math.isfinite(kscale) and kscale > 0 else 1.0
    bounds = {"kp": (0.0, 20 * kscale), "ki": (0.0, 20 * kscale / T), "kd": (0.0, 5 * kscale * T), "ff": (0.0, 2 * kscale), "ulim": (0.1 * u_max, u_max)}
    params = []
    for r in roles:
        lo, hi = bounds[r]
        init = float(rng.uniform(lo + 0.02 * (hi - lo), lo + 0.3 * (hi - lo))) if r != "ulim" else hi
        params.append({"name": str(rng.choice(NAMES[r])) + ("" if rng.random() < 0.7 else f"_{int(rng.integers(9))}"), "role": r,
                       "min": lo, "max": hi, "init": init, "max_delta": (hi - lo) * float(rng.uniform(0.05, 0.3))})
    unit = str(rng.choice(UNITS[kind]))
    plant = {"standin": True, "seed": seed, "kind": kind, "num": [float(x) for x in np.ravel(G.num[0][0])], "den": [float(x) for x in np.ravel(G.den[0][0])],
             "delay_s": L, "pade": [list(map(float, x)) for x in control.pade(L, 3)] if L > 0 else None,
             "u_max": u_max, "deadzone": dz, "noise_std": noise, "sample_s": dt, "range": rngphys, "unit": unit, "cause": cause}
    app = {"params": params, "channels": {"sp": f"sp_{unit}", "y": f"y_{unit}", "u": "u"}, "unit": unit}
    link = {"sample_s": dt, "u_max": u_max, "range": rngphys}
    # reference：真对象上粗搜（无噪声），记最好指标与参数
    ref = reference(plant, app, amp_ref)
    spec, feasible, why = _spec(rng, ref, cause, T, L, plant)
    plant |= {"reference": ref, "feasible": feasible, "infeasible_reason": why if not feasible else None}
    if out:
        d = pathlib.Path(out)
        d.mkdir(parents=True, exist_ok=True)
        import yaml
        (d / "app.yaml").write_text(yaml.safe_dump(app, allow_unicode=True), "utf-8")
        (d / "link.yaml").write_text(yaml.safe_dump(link, allow_unicode=True), "utf-8")
        (d / "spec.txt").write_text(spec, "utf-8")
        (d / "plant.json").write_text(json.dumps(plant, ensure_ascii=False, indent=1), "utf-8")
    return {"app": app, "link": link, "spec": spec, "plant": plant}


def _rescale(G, a):
    """G(s) → G(a·s)。"""
    import control
    num, den = np.ravel(G.num[0][0]), np.ravel(G.den[0][0])
    nn = num * a ** np.arange(len(num) - 1, -1, -1)
    dd = den * a ** np.arange(len(den) - 1, -1, -1)
    return control.tf(nn / dd[0], dd / dd[0])


def _spec(rng, ref, cause, T, L, plant):
    m = ref["metrics"]
    fin = all(math.isfinite(m[k]) for k in ("ss_err_pct", "overshoot_pct", "settle_s"))
    if cause is None and fin:
        ss, os_, st = max(2 * m["ss_err_pct"], 1.0), max(m["overshoot_pct"] + 10, 5.0), max(2.0 * m["settle_s"], 3 * plant["sample_s"])
    else:                                           # 故意卡死：时间指标定得比物理上能做到的还快
        ss, os_ = 1.0, 2.0
        st = max(0.25 * (m["settle_s"] if math.isfinite(m["settle_s"]) else T), plant["sample_s"] * 2)
        if cause == "delay":
            st = min(st, 0.5 * L)
    txt = f"要求：稳态误差不超过 {ss:.3g}%，超调量不超过 {os_:.3g}%，调节时间不超过 {st:.3g} s。"
    sp = AT.parse_spec(txt)
    ok = not AT.meets(m, sp) and fin
    why = cause or ("not_reached" if not ok else None)
    return txt, bool(ok), why


class SimBoard:
    """替身板：照真值仿真（整数拍时延、饱和、死区、噪声），写参超 max_delta 拒写，不暴露真值。"""

    def __init__(self, plant: dict, app: dict, seed: int):
        import control
        self._p = plant
        self._decl = {d["name"]: d for d in app["params"]}
        self._vals = {d["name"]: d["init"] for d in app["params"]}
        self._rng = np.random.default_rng(seed + 104729)
        self._m = AT.LinModel(control.c2d(control.tf(plant["num"], plant["den"]), plant["sample_s"]), round(plant["delay_s"] / plant["sample_s"]))
        self.rejected = 0

    def read_params(self):
        return dict(self._vals)

    def write_param(self, name, v):
        d = self._decl[name]
        if abs(v - self._vals[name]) > d["max_delta"] * (1 + 1e-9) or not d["min"] - 1e-12 <= v <= d["max"] + 1e-12:
            self.rejected += 1
            raise ValueError("rejected")
        self._vals[name] = float(v)

    def step(self, amp, n, noise=True):
        p = {self._decl[k]["role"]: v for k, v in self._vals.items()}
        return simulate(self._p, self._m, p, amp, n, self._rng if noise else None)


def simulate(plant, model, p, amp, n, rng=None):
    f = model.stepper()
    dz, sd = plant["deadzone"], plant["noise_std"]

    def g(u):
        ue = 0.0 if abs(u) < dz else u - math.copysign(dz, u)
        y = f(ue)
        return y + (float(rng.normal(0, sd)) if rng is not None and sd else 0.0)
    dt = plant["sample_s"]
    r = np.full(n, float(amp))
    y, u = AT.pid_loop(g, p, r, dt, plant["u_max"])
    return np.arange(n) * dt, r, y, u


def reference(plant, app, amp, tries=260):
    import control
    m = AT.LinModel(control.c2d(control.tf(plant["num"], plant["den"]), plant["sample_s"]), round(plant["delay_s"] / plant["sample_s"]))
    T = plant["sample_s"]
    n = 900
    decl = [dict(d) for d in app["params"]]
    rng = np.random.default_rng(plant["seed"] + 31337)
    best = AT.design(m, decl, amp, T, n, plant["u_max"], rng, {d["role"]: d["init"] for d in decl}, tries=tries)
    t, r, y, u = simulate(plant, m, best, amp, n)
    met = AT.metrics(t, r, y, amp)
    return {"params_roles": best, "metrics": met, "cost": AT.cost(met), "amp": amp, "n": n}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--kind", default="any", choices=["pos", "vel", "temp", "any"])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    make(a.seed, a.kind, a.out)
    print(f"STAND-IN randplant seed={a.seed} → {a.out}")
