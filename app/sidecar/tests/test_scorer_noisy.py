"""fw-scorer-noisy：判卷按 randplant noise_std 带噪闭环、加噪前真输出打分（K 个判卷专用固定噪声种子，取均值）。
- 随机二阶欠阻尼对象 + 大 kd + 传感器噪声 → 执行器长时间饱和：无噪仿真偏爱大 kd，带噪真值必须判 kd=0 更好；
- 结果确定（同输入两次一致，不受全局随机状态影响）；
- 「按观测条件算」的对照分数只作诊断，不改判卷；
- 28708004 回归（通用对象参数，判卷里没有任何按种子的特殊处理）；
- 真值不外泄：check_no_truth_leak 仍通过。"""
import json
import math
import pathlib
import subprocess
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import tunegate_grade as G  # noqa: E402
import tunegate_plant as RP  # noqa: E402

from dzbench.tuning import autotune as AT  # noqa: E402


def _noisy_kd_case(rng):
    """随机欠阻尼二阶对象；噪声取到 kd·√2·σ/dt ≈ 3·u_max（微分把噪声放大到打满执行器）。"""
    import control
    K, wn, z = float(rng.uniform(0.5, 5)), float(rng.uniform(2, 20)), float(rng.uniform(0.1, 0.3))
    dt = float(1 / (wn * rng.uniform(15, 40)))
    amp = float(rng.uniform(0.5, 50))
    umax = amp / K * float(rng.uniform(1.5, 3))
    num, den = [K * wn * wn], [1.0, 2 * z * wn, wn * wn]
    kp, kd = 0.5 / K, (1 - z) * 2 / (K * wn)
    hi = {"kp": kp, "ki": kp * wn * 0.5, "kd": kd}
    sd = 3 * umax * dt / (kd * math.sqrt(2))
    plant = {"num": num, "den": den, "delay_s": 0.0, "sample_s": dt, "u_max": umax, "deadzone": 0.0, "noise_std": sd,
             "seed": int(rng.integers(1 << 30)), "range": 4 * amp, "unit": None, "kind": "vel"}
    m = AT.LinModel(control.c2d(control.tf(num, den), dt), 0)
    n = int(8 / (z * wn) / dt * 0.6)
    return plant, m, hi, dict(hi, kd=0.0), amp, n


def _nf(plant, m, p, amp, n):
    t, r, y, u = RP.simulate(plant, m, p, amp, n)
    return AT.cost(AT.metrics(t, r, y, amp))


@pytest.mark.parametrize("draw", range(4))
def test_high_kd_noise_saturation_ranked_by_noisy_truth(draw):
    plant, m, hi, lo, amp, n = _noisy_kd_case(np.random.default_rng(1000 + draw))
    H, L = G.noisy_truth(plant, m, hi, amp, n), G.noisy_truth(plant, m, lo, amp, n)
    assert _nf(plant, m, hi, amp, n) < _nf(plant, m, lo, amp, n)       # 无噪仿真：大 kd 看着更好（旧判卷的盲区）
    assert H["sat_frac"] > 0.5 > L["sat_frac"]                         # 噪声经微分打满执行器
    assert H["cost"] > L["cost"]                                       # 带噪真值：kd=0 才真更好
    assert H["k"] == G.NOISE_K and H["p75"] >= min(H["cost"], H["p75"])


def test_noise_free_plant_equals_noise_free_score():
    plant, m, hi, _, amp, n = _noisy_kd_case(np.random.default_rng(7))
    plant = dict(plant, noise_std=0.0)
    r = G.noisy_truth(plant, m, hi, amp, n)
    assert r["k"] == 1 and r["cost"] == pytest.approx(_nf(plant, m, hi, amp, n)) and r["observed"] == pytest.approx(r["cost"])


def test_deterministic_and_independent_of_global_rng():
    plant, m, hi, _, amp, n = _noisy_kd_case(np.random.default_rng(3))
    np.random.seed(1)
    a = G.noisy_truth(plant, m, hi, amp, n)
    np.random.seed(2)
    np.random.default_rng(99).normal(size=100)
    b = G.noisy_truth(plant, m, hi, amp, n)
    assert {k: a[k] for k in ("cost", "p75", "observed", "sat_frac")} == {k: b[k] for k in ("cost", "p75", "observed", "sat_frac")}
    assert len(set(G.NOISE_SEEDS)) == G.NOISE_K


def _write(d, plant, m, app, amp, n):
    ref = {"amp": amp, "n": n, "cost": 0.0, "params_roles": {q["role"]: q["init"] for q in app["params"]}, "metrics": {}}
    plant = dict(plant, reference=ref, feasible=True, infeasible_reason=None, gen_kind="any")
    (pathlib.Path(d) / "plant.json").write_text(json.dumps(plant), "utf-8")


@pytest.mark.parametrize("swap", [False, True])
def test_grade_better_than_initial_uses_noisy_truth(tmp_path, swap):
    plant, m, hi, lo, amp, n = _noisy_kd_case(np.random.default_rng(1001))
    app = {"params": [{"name": f"p{i}", "role": r, "min": 0.0, "max": 10 * v + 1, "init": v, "max_delta": 1e9}
                      for i, (r, v) in enumerate(hi.items())]}
    _write(tmp_path, plant, m, app, amp, n)
    init, best = (lo, hi) if swap else (hi, lo)
    res = {"initial": {"roles": init}, "best": {"roles": best}, "verdict": "fail", "category": "unconfirmed",
           "pass_basis": "", "amp": amp, "n": n}
    g = G.grade(str(tmp_path), 1, res, app, "要求：稳态误差不超过 50%。")
    better = [e for e in g["errors"] if e.startswith("没比初值好")]
    assert bool(better) == swap                                      # 大 kd → kd=0 算改善；反过来算变差
    assert g["noise_free"]["best"] != g["cost"]["best"]              # 无噪分只作诊断字段
    assert set(g["sat_frac"]) == {"initial", "best"} and set(g["observed"]) == {"initial", "best"}


def test_regression_seed_28708004_tuner_result_better_under_noisy_truth():
    """通用回归：randplant 种子 28708004 的对象（高 kd 初值 + 传感器噪声），整定器结果在带噪真值上必须优于初值。"""
    import tunegate as TG
    r = TG.one(28708004, "any")
    assert r["feasible"] is True
    assert r["cost"]["best"] < r["cost"]["initial"]
    assert r["sat_frac"]["initial"] > 0.5
    assert not any(e.startswith("没比初值好") for e in r["errors"])


def test_no_truth_leak():
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "check_no_truth_leak.py")], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    src = (ROOT / "tools" / "tunegate_grade.py").read_text("utf-8")
    assert "28708004" not in src                                      # 判卷无按种子的特殊处理


def test_worse_than_initial_not_reverted_is_hard_fail_rc(tmp_path, monkeypatch):
    """带噪真值比初值差、又没退回初值：grade 标 worse_not_reverted，tunegate 退出码非 0。"""
    plant, m, hi, lo, amp, n = _noisy_kd_case(np.random.default_rng(1001))
    app = {"params": [{"name": f"p{i}", "role": r, "min": 0.0, "max": 10 * v + 1, "init": v, "max_delta": 1e9}
                      for i, (r, v) in enumerate(lo.items())]}
    _write(tmp_path, plant, m, app, amp, n)
    res = {"initial": {"roles": lo}, "best": {"roles": hi}, "verdict": "fail", "category": "unconfirmed", "pass_basis": "", "amp": amp, "n": n}
    g = G.grade(str(tmp_path), 1, res, app, "要求：稳态误差不超过 50%。")
    assert g["worse_not_reverted"] and g["bucket"] == "worse_not_reverted" and not g["ok"]
    same = G.grade(str(tmp_path), 1, res | {"best": {"roles": dict(lo)}}, app, "要求：稳态误差不超过 50%。")
    assert not same["worse_not_reverted"]                            # 退回初值不算
    import tunegate as TG
    monkeypatch.setattr(TG, "one", lambda s, k: g | {"seed": s, "rejected_writes": 0, "secs": 0.0, "amp_reduced": False})
    monkeypatch.setenv("TUNEGATE_WORSE_HARD", "1")
    assert TG.main(["--seed", "1"]) != 0
