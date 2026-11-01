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
            assert res["improvement"] == "worse" and res["default_action"] == "keep_initial" and res["reason"] == "kept_initial"
            assert res["improvement_info"]["causes"] and res["message_zh"] == AT.KEPT_INITIAL_ZH
            if res["verdict"] != "pass":
                assert res["causes"], res                      # 退回初值也要给原因
        else:
            fc = res["final_check"]                              # 交付的参数在 n / 2n / 4n 每个终验窗口都不比初值差
            assert len(fc["windows"]) >= 2 and all(w["best_cost"] <= w["initial_cost"] for w in fc["windows"]), fc
        for it in res["items"]:
            assert "margin" in it


def test_tuner_pass_agrees_with_grader_4030():
    r = TG.one(4030, "any")                                      # 曾经：整定器说 pass，判卷说比初值差
    assert not (r["verdict"] == "pass" and not r["ok"]), r


def _tune(seed, monkeypatch, k):
    import tempfile

    import tunegate_plant as RP
    import yaml
    monkeypatch.setattr(AT, "NOISE_BAND_K", k)
    with tempfile.TemporaryDirectory() as d:
        RP.make(seed, "any", d)
        app = yaml.safe_load(open(f"{d}/app.yaml", encoding="utf-8"))
        link = yaml.safe_load(open(f"{d}/link.yaml", encoding="utf-8"))
        spec = open(f"{d}/spec.txt", encoding="utf-8").read()
        return AT.autotune(G.board(d, app, seed, "randplant"), app, link, spec, seed)


def test_improvement_within_noise_band_is_unconfirmed(monkeypatch):
    """配对比较不确定（改善没超出噪声带）：卡上不说已改善，写明噪声大、建议保留初值或加长采样，不默认采用。"""
    from dzbench.agent import reason_codes as RC
    ok = _tune(3001, monkeypatch, 0.0)                           # 这个种子整定后明显比初值好
    assert not ok["kept_initial"] and ok["improvement_confirmed"] is True and ok["adopt_default"] is True, ok["final_check"]
    assert "reason" not in ok and AT.UNCONFIRMED_ZH not in ok["verdict_zh"]
    un = _tune(3001, monkeypatch, 1e12)                          # 同一次比较，噪声带放大到盖过改善
    fc = un["final_check"]
    assert fc["noise_band"] >= 0 and un["improvement_confirmed"] is False, fc
    assert un["reason"] == "improvement_unconfirmed" and un["message_zh"] == AT.UNCONFIRMED_ZH and un["unconfirmed_causes"]
    assert un["verdict_zh"].startswith(AT.UNCONFIRMED_ZH) and "已改善" not in un["verdict_zh"] + un["pass_basis"]
    assert un["adopt_default"] is False and un["improvement"] == "inconclusive" and un["default_action"] == "keep_initial"
    ii = un["improvement_info"]
    assert ii["reason"] == "improvement_unconfirmed" and ii["message_zh"] == AT.UNCONFIRMED_ZH and ii["causes"] and ii["default_action"] == "keep_initial"
    assert ok["improvement"] == "confirmed" and ok["default_action"] == "adopt" and ok["improvement_info"]["reason"] is None
    t = RC.table()["improvement_unconfirmed"]
    assert t["message_zh"] == AT.UNCONFIRMED_ZH and t["causes"]


def test_noise_amplified_saturation_function():
    """#159 只看可观测量：初值 kd×噪声斜率顶限幅、饱和占比高，调后 kd 小了、饱和少了 → 报原因并给前后占比。"""
    rng = np.random.default_rng(1)
    y0 = 1.0 + rng.normal(0, 0.01, 2000)
    u0 = np.where(rng.random(2000) < 0.8, 1.0, 0.2)
    ub = np.where(rng.random(2000) < 0.1, 1.0, 0.2)
    c = AT.noise_amplified_saturation({"kd": 1.0}, u0, y0, {"kd": 0.0}, ub, 1.0, 0.005, {})
    assert c and c["code"] == "noise_amplified_saturation" and c["sat_frac_initial"] > 0.7 and c["sat_frac_best"] < 0.2
    assert "初值微分过大，噪声被放大，执行器约" in c["message_zh"] and "已减小微分" in c["message_zh"]
    assert AT.noise_amplified_saturation({"kd": 1.0}, u0, y0, {"kd": 1.0}, ub, 1.0, 0.005, {}) is None       # 微分没减小
    assert AT.noise_amplified_saturation({"kd": 1.0}, ub, y0, {"kd": 0.0}, ub, 1.0, 0.005, {}) is None       # 初值没怎么饱和
    assert AT.noise_amplified_saturation({"kd": 1.0}, u0, y0, {"kd": 0.0}, ub, 1.0, 0.005, {"noise_sat_frac_min": 0.95}) is None   # 声明门限优先


def _noisy_kd_plant(seed, d, noise_rel, kd_mult):
    """随机对象 + 「噪声大、初值微分大」的工况（照 #159 那类：微分把噪声放大到顶限幅）。种子随机取，不认具体种子。"""
    import json

    import tunegate_plant as RP
    import yaml
    RP.make(seed, "any", d)
    app = yaml.safe_load(open(f"{d}/app.yaml", encoding="utf-8"))
    link = yaml.safe_load(open(f"{d}/link.yaml", encoding="utf-8"))
    kd = next((x for x in app["params"] if x["role"] == "kd"), None)
    if kd is None:
        return None
    pl = json.load(open(f"{d}/plant.json", encoding="utf-8"))
    pl["noise_std"] = noise_rel * float(link["max_step"])
    json.dump(pl, open(f"{d}/plant.json", "w", encoding="utf-8"))
    if noise_rel:
        kd["init"] = min(float(kd["max"]), kd_mult * float(link["u_max"]) * float(link["sample_s"]) / (pl["noise_std"] * 2 ** 0.5))
    yaml.safe_dump(app, open(f"{d}/app.yaml", "w", encoding="utf-8"), allow_unicode=True)
    return app, link, open(f"{d}/spec.txt", encoding="utf-8").read()


def test_noise_amplified_saturation_on_random_plants():
    import tempfile
    seeds = [int(s) for s in np.random.default_rng(159).integers(10_000_000, 99_999_999, 40)]
    hits = 0
    for seed in seeds:
        with tempfile.TemporaryDirectory() as d:
            got = _noisy_kd_plant(seed, d, 0.0075, 2.0)
            if got is None:
                continue
            app, link, spec = got
            r = AT.autotune(G.board(d, app, seed, "randplant"), app, link, spec, seed)
            for c in r["tuning_causes"]:
                assert c["code"] == "noise_amplified_saturation" and c["sat_frac_best"] < c["sat_frac_initial"], c
                assert c["kd_best"] < c["kd_initial"] and c["message_zh"] in r["pass_basis"]
                assert r["improvement"] in ("confirmed", "inconclusive")       # 退回初值时不说“已减小微分”
                hits += 1
        if hits >= 2:
            break
    assert hits >= 2, seeds
    with tempfile.TemporaryDirectory() as d:                     # 无噪声：不报这个原因
        for seed in seeds:
            got = _noisy_kd_plant(seed, d, 0.0, 1.0)
            if got:
                app, link, spec = got
                r = AT.autotune(G.board(d, app, seed, "randplant"), app, link, spec, seed)
                assert not r["tuning_causes"], r["tuning_causes"]
                break
    from dzbench.agent import reason_codes as RC
    t = RC.table()["noise_amplified_saturation"]
    assert t["kind"] == "tune" and t["message_zh"] and t["causes"]
