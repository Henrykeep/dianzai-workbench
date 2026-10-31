#!/usr/bin/env python3
"""#78 门禁的对象：对象本体来自 tools/randplant.py（嵌入式开发-2，与 plant: 声明共用 tools/plantmodel.py）。
本文件只做判卷侧的事：
  - 把 randplant.gen(seed) 转成整定器读的 app / link / spec（参数名随机化，只给角色，不给真值）；
  - 约 30% 的种子在对象上叠加一个"做不到"的原因（saturation / delay / nonminimum_phase），用来考原因分类；
  - Python 仿真板 SimBoard（拒写超 max_delta 的写参）和 reference（真值上粗搜的参考代价，只给判卷）。
随机数全部来自 numpy Generator(seed)，同一 seed 完全可复现。
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app" / "sidecar"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from dzbench.tuning import autotune as AT  # noqa: E402
import randplant  # noqa: E402

NAMES = {"kp": ["kp", "p_gain", "gain_p", "k1", "pos_k"], "ki": ["ki", "i_gain", "k2", "integ"], "kd": ["kd", "d_gain", "k3", "damp"],
         "ff": ["ff", "kff", "feedfwd"], "ulim": ["ulim", "out_max", "lim"]}
CAUSES = ("saturation", "delay", "nonminimum_phase")


def make(seed: int, kind: str = "any", out: str | None = None) -> dict:
    import control
    rp = randplant.gen(seed, "1-3", kind)
    rng = np.random.default_rng(seed + 7919)
    G = control.tf(rp["tf"]["num"], rp["tf"]["den"])
    kind = rp["kind"]
    integ = bool(rp["integrator"])
    T = float(rp["tau_s"])
    K = abs(float(rp["gain"]))
    u_max = float(rp["sat"])
    cause = str(rng.choice(CAUSES)) if rng.random() < 0.3 else None
    L = float(rp["delay_s"]) if cause != "delay" else float(rng.uniform(2.0, 4.0) * T)
    if cause == "nonminimum_phase":
        G = G * control.tf([-T / float(rng.uniform(0.6, 1.5)), 1], [1])
    rngphys = float(rp["range"])
    amp_ref = rngphys / 4
    if cause == "saturation":
        k_amp = K if not integ else 1.0
        u_max = float(abs(amp_ref / k_amp) * rng.uniform(0.05, 0.2))
    dt = float(rp["dt_s"])
    dz = float(min(rp["deadzone"], 0.02 * u_max))
    roles = ["kp"] + [r for r in ("ki", "kd", "ff", "ulim") if rng.random() < {"ki": 0.8, "kd": 0.5, "ff": 0.25, "ulim": 0.2}[r]]
    rg = rp["ranges"]
    bounds = {"kp": tuple(rg["kp"]), "ki": tuple(rg["ki"]), "kd": tuple(rg["kd"]), "ff": (0.0, 2 * rg["kp"][1] / 20), "ulim": (0.1 * u_max, u_max)}
    params = []
    for r in roles:
        lo, hi = map(float, bounds[r])
        init = float(rp["init"][r]) if r in rp["init"] else (hi if r == "ulim" else float(rng.uniform(lo, lo + 0.3 * (hi - lo))))
        params.append({"name": str(rng.choice(NAMES[r])) + ("" if rng.random() < 0.7 else f"_{int(rng.integers(9))}"), "role": r,
                       "min": lo, "max": hi, "init": init, "max_delta": (hi - lo) * float(rng.uniform(0.05, 0.3))})
    unit = rp["unit"]
    plant = {"source": "tools/randplant.py", "seed": seed, "kind": kind, "num": [float(x) for x in np.ravel(G.num[0][0])], "den": [float(x) for x in np.ravel(G.den[0][0])],
             "delay_s": L, "u_max": u_max, "deadzone": dz, "noise_std": float(rp["noise_std"]), "sample_s": dt, "range": rngphys, "unit": unit,
             "cause": cause, "randplant_feasible": rp["feasible"], "randplant_reason": rp["reason"]}
    app = {"params": params, "channels": {"sp": f"sp_{unit}", "y": f"y_{unit}", "u": "u"}, "unit": unit}
    link = {"sample_s": dt, "u_max": u_max, "range": rngphys}
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
    """仿真板：照真值仿真（整数拍时延、饱和、死区、噪声），写参超 max_delta 拒写，不暴露真值。"""

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
    ap.add_argument("--kind", default="any", choices=list(randplant.UNITS))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    make(a.seed, a.kind, a.out)
    print(f"tunegate plant seed={a.seed} → {a.out}")
