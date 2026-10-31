#!/usr/bin/env python3
"""#78 门禁的对象：对象本体来自 tools/randplant.py（嵌入式开发-2，与 plant: 声明共用 tools/plantmodel.py）。
本文件只做判卷侧的事：
  - 把 randplant.gen(seed) 转成整定器读的 app / link / spec（参数名随机化，只给角色，不给真值）；
  - 做不到的原因（饱和 / 滞后 / 不稳定零点 …）由 randplant 自己注入并给出类别，这里只映射到整定器的类别名；
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



ROLE = {"P": "kp", "I": "ki", "D": "kd", "FF": "ff", "LIM": "ulim"}
CAT = {"unstable_zero": "nonminimum_phase", "delay_too_large": "delay", "saturation": "saturation"}


def make(seed: int, kind: str = "any", out: str | None = None) -> dict:
    """randplant.gen(seed) 原样取对象、可调参数（随机名 + 角色）、题面指标和可行性；这里只换成整定器读的格式 + 判卷用的参考代价。"""
    rp = randplant.gen(seed, "1-3", kind)
    params = [{"name": nm, "role": ROLE[r], "min": float(rp["ranges"][nm][0]), "max": float(rp["ranges"][nm][1]),
               "init": float(rp["init"][nm]), "max_delta": float(rp["max_delta"][nm])} for r, nm in rp["roles"].items()]
    unit = rp["unit"]
    plant = {"source": "tools/randplant.py", "seed": seed, "kind": rp["kind"], "num": [float(x) for x in rp["tf"]["num"]],
             "den": [float(x) for x in rp["tf"]["den"]], "delay_s": float(rp["delay_s"]), "u_max": float(rp["sat"]),
             "deadzone": float(rp["deadzone"]), "noise_std": float(rp["noise_std"]), "sample_s": float(rp["dt_s"]),
             "range": float(rp["sensor_range"]), "unit": unit}
    app = {"params": params, "channels": {"sp": "sp", "y": "y", "u": "u"}, "unit": unit}
    link = {"sample_s": plant["sample_s"], "u_max": plant["u_max"], "sensor_range": plant["range"], "max_step": float(rp["max_step"])}
    ref = reference(plant, app, float(rp["reference"]["step_amp"]))
    spec, feasible = rp["spec_text"], bool(rp["feasible"])
    cat = CAT.get(rp.get("reason_category") or "", rp.get("reason_category"))
    plant |= {"reference": ref, "feasible": feasible, "infeasible_reason": None if feasible else cat, "reason_zh": rp.get("reason")}
    if out:
        d = pathlib.Path(out)
        d.mkdir(parents=True, exist_ok=True)
        import yaml
        (d / "app.yaml").write_text(yaml.safe_dump(app, allow_unicode=True), "utf-8")
        (d / "link.yaml").write_text(yaml.safe_dump(link, allow_unicode=True), "utf-8")
        (d / "spec.txt").write_text(spec, "utf-8")
        (d / "plant.json").write_text(json.dumps(plant, ensure_ascii=False, indent=1), "utf-8")
    return {"app": app, "link": link, "spec": spec, "plant": plant}






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
