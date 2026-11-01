"""整定策略组：按证据诊断原因、增益下限、收敛 / 预算 / 边界停、代价对齐题面、初值已达标不改参数；判卷汇总与硬门禁。"""
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import tunegate as TG  # noqa: E402
import tunegate_grade as G  # noqa: E402

from dzbench.tuning import autotune as AT  # noqa: E402

SP = {"ss_err_pct": 2.0, "overshoot_pct": 10.0, "settle_s": None}


def test_diagnose_by_evidence_not_fixed_order():
    n = 400
    bu = np.full(n, 0.5)                                         # 没顶限幅
    by = np.zeros(n)
    by[200:] = 1.0 - np.exp(-np.arange(n - 200) / 10.0)         # 200 拍纯滞后，上升 ~10 拍
    by[190:200] = -0.001
    c = AT.diagnose({}, bu, by, 1.0, 1.0, 4.0, {"overshoot_pct": 0.0}, SP)
    assert c[0]["code"] == "delay" and c[0]["evidence"] == "strong", c
    assert all(set(x) >= {"code", "evidence", "basis_zh"} and x["evidence"] in AT.LEVEL for x in c)
    sat = AT.diagnose({"K": 0.5, "integrating": False}, bu, by, 1.0, 1.0, 4.0, {"overshoot_pct": 0.0}, SP)
    assert {x["code"] for x in sat} >= {"delay", "saturation"}
    assert AT._close({"evidence": "strong"}, {"evidence": "strong"}) and not AT._close({"evidence": "strong"}, {"evidence": "weak"})


def test_spec_cost_follows_spec_and_gain_floor():
    ok = {"ss_err_pct": 1.0, "overshoot_pct": 5.0, "settle_s": 1.0, "iae": 0.9}
    bad = {"ss_err_pct": 30.0, "overshoot_pct": 0.0, "settle_s": 1.0, "iae": 0.1}
    assert AT.spec_cost(ok, SP) < AT.spec_cost(bad, SP)          # 低 IAE 但超题面不算更好
    decl = [{"role": "kp", "min": 0.0, "max": 10.0}, {"role": "ki", "min": 0.0, "max": 10.0}, {"role": "kd", "min": 0.0, "max": 1.0}]
    fl = AT.gain_floor(decl, [{"kp": 1.0, "ki": 2.0, "kd": 0.1}, {"kp": 5.0, "ki": 0.0, "kd": 0.0}])
    # 下限 = max(声明 min, FLOOR_FRAC×候选最大, FLOOR_INIT×初值)；kd 不设下限
    assert fl["kp"] == max(AT.FLOOR_FRAC * 5.0, AT.FLOOR_INIT * 1.0) > 0
    assert fl["ki"] == max(AT.FLOOR_FRAC * 2.0, AT.FLOOR_INIT * 2.0) > 0 and "kd" not in fl
    hi = AT.gain_floor([dict(decl[0], min=0.5)], [{"kp": 1.0}])
    assert hi["kp"] == 0.5                                       # 声明 min 更高时取声明 min
    for d in decl:
        d["init"] = 0.0
    assert AT._clip_floor({"kp": 1e-9, "ki": 1e-9, "kd": 0.0}, decl, fl)["kp"] == fl["kp"]


def test_initial_already_meets_spec_is_unchanged_not_tuned():
    r = TG.one(3005, "any")                                      # 固定种子：初值已满足题面
    assert r["unchanged"] and r["stop_reason"] == "converged" and r["ok"], r


def test_stop_reason_and_causes_on_card():
    r = TG.one(3010, "any")                                      # 固定种子：时延做不到
    assert r["stop_reason"] in AT.STOP_ZH and r["verdict"] != "pass" and r["category"] == r["cause"], r


def test_grader_cause_must_match_and_early_stop_is_hard(monkeypatch, capsys):
    real = AT.autotune
    monkeypatch.setattr(AT, "autotune", lambda *a, **k: real(*a, **k) | {"category": "unconfirmed"})
    r = TG.one(3010, "any")
    assert not r["ok"] and any("原因对不上" in e for e in r["errors"]), r
    rs = [{"seed": 1, "ok": False, "errors": ["x"], "early_stop_not_pass": True, "bucket": "early_stop_not_pass"}]
    assert G.summarize(rs)["early_stop_not_pass"] == [1]
    monkeypatch.setattr(TG, "one", lambda s, k: rs[0])
    assert TG.main(["--seed", "1"]) == 1
    assert "提前停未达标 1" in capsys.readouterr().out


def test_never_deliver_worse_than_initial():
    """绝不交付比初值差的参数：终验（窗口加倍、本机实测代价）里调后不如初值 → 退回初值，卡上写「调参未能改善，已保留初值」。
    真随机对象（randplant，经真仿真板）逐个跑；判定只看整定器自己的实测，不读真值。"""
    import tempfile
    import yaml
    import tunegate_plant as RP
    for seed in (4030, 3003, 4037):
        with tempfile.TemporaryDirectory() as d:
            RP.make(seed, "any", d)
            app = yaml.safe_load(open(f"{d}/app.yaml", encoding="utf-8"))
            link = yaml.safe_load(open(f"{d}/link.yaml", encoding="utf-8"))
            spec = open(f"{d}/spec.txt", encoding="utf-8").read()
            res = AT.autotune(G.board(d, app, seed, "randplant"), app, link, spec, seed)
        if res.get("kept_initial"):
            assert res["best"]["roles"] == res["initial"].get("roles", res["best"]["roles"]) or \
                res["best"]["params"] == res["initial"]["params"], res
            assert AT.KEPT_INITIAL_ZH in res["verdict_zh"] and AT.KEPT_INITIAL_ZH in res["pass_basis"], res
            assert res["unchanged"] and not res["tuned"]
            if res["verdict"] != "pass":
                assert res["causes"], res                      # 退回初值也要给原因
        else:
            fc = res["final_check"]                              # 交付的参数在终验里不比初值差
            assert fc["best_cost"] <= fc["initial_cost"], fc
        for it in res["items"]:
            assert "margin" in it


def test_tuner_pass_agrees_with_grader_4030():
    r = TG.one(4030, "any")                                      # 曾经：整定器说 pass，判卷说比初值差
    assert not (r["verdict"] == "pass" and not r["ok"]), r
