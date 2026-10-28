"""调参护栏 / 风险分级 / 严格解析 / 固定种子基准（全部离线）。"""
import math

import pytest

from dzbench.agent import bench, risk
from dzbench.agent.guard import GuardError, TuneGuard, good_enough, key_samples, parse_reply
from dzbench.agent.tuning import StepMetrics, step_metrics


def M(os_=0.0, sse=0.0, settle=0.3, osc=0, iae=0.1):
    return StepMetrics(True, target=1.0, y0=0.0, rise_s=0.1, overshoot_pct=os_, settling_s=settle, sse_pct=sse,
                       oscillations=osc, iae=iae)


def test_step_limits_both_directions_abs_and_zero_start():
    g = TuneGuard({"kp": (0, 2), "ki": (0, 20)}, sim=False)
    assert g.check("kp", 0.1, 99)[0] == pytest.approx(0.15)        # ×1.5
    g.proposed_this_round = None
    assert g.check("kp", 1.0, 0.0)[0] == pytest.approx(0.8)        # 降幅 ×0.7 后再受绝对步长 0.2 限
    g.proposed_this_round = None
    assert g.check("ki", 0.0, 250)[0] == pytest.approx(0.4)        # 0 起步：量程 × 2%
    with pytest.raises(GuardError) as e:
        g.check("kp", 0.1, 0.12)                                   # 本轮已改过 ki → 每轮一项
    assert e.value.code == "one_gain"
    for bad in (True, math.nan, math.inf):
        g.proposed_this_round = None
        with pytest.raises(GuardError):
            g.check("kp", 0.1, bad)


def test_program_decides_done_rollback_blocked_direction_and_round_cap():
    g = TuneGuard({"kp": (0, 2)}, sim=False)
    assert g.record(M(os_=20, iae=0.3), {"kp": 0.1})["action"] == "continue"
    v = g.record(M(os_=35, osc=2, iae=0.6), {"kp": 0.15})          # 加 kp 变差
    assert ("kp", 1) in g.blocked and v["action"] == "rollback" and v["auto"] is False   # 实机回滚要人点
    with pytest.raises(GuardError) as e:
        g.check("kp", 0.15, 0.2)
    assert e.value.code == "bad_direction"
    g.record(M(), {"kp": 0.1}); v = g.record(M(), {"kp": 0.1})
    assert v["action"] == "done" and g.stopped
    with pytest.raises(GuardError):
        g.check("kp", 0.1, 0.09)                                   # 结束后不再接受提议
    g2 = TuneGuard({"kp": (0, 2)}, sim=False)
    acts = [g2.record(M(os_=20 + i), {"kp": 0.1 + i * 0.01})["action"] for i in range(8)]
    assert acts[-1] == "stop" and "8 轮" in g2.stopped
    assert TuneGuard({}, sim=True).profile.auto_rollback


def test_battery_and_temperature_stop():
    g = TuneGuard({}, sim=False, limits={"vbat_min": 7.0, "temp_max": 70})
    assert g.record(M(os_=20), {"kp": 1}, {"vbat": 6.8})["action"] == "stop" and "电池" in g.stopped
    g = TuneGuard({}, sim=False, limits={"vbat_min": None, "temp_max": 70})
    assert g.record(M(os_=20), {"kp": 1}, {"temp_c": 75})["action"] == "stop"


def test_overshoot_normalised_by_step_when_setpoint_is_zero():
    # 平衡角/球位置类回路：目标 0，从 10 掉到 0，冲到 -2 → 超调 20%（按阶跃幅度，不是按 sp）
    t = [i * 0.01 for i in range(300)]
    sp = [10.0 if i < 50 else 0.0 for i in range(300)]
    y = [10.0 if i < 50 else (-2.0 if i < 80 else 0.0) for i in range(300)]
    m = step_metrics(t, y, sp)
    assert m.ok and m.overshoot_pct == pytest.approx(20, abs=0.5) and good_enough(m) is False


def test_strict_reply_parsing():
    assert parse_reply('想了想……\n{"action":"PROPOSE","param":"kp","value":0.12,"reason":"超调小"}') == \
        {"action": "PROPOSE", "param": "kp", "value": 0.12, "reason": "超调小"}
    assert parse_reply('{"action":"observe"}')["action"] == "OBSERVE"
    for bad in ('kp 改成 0.2 吧', '{"action":"PROPOSE","param":"kp","value":true}', '{"action":"PROPOSE","param":"kp","value":NaN}',
                '{"action":"PROPOSE","param":"kp","value":1e99}', '{"action":"GO"}'):
        with pytest.raises(GuardError):
            parse_reply(bad)


def test_key_samples_keep_extremes_and_jumps():
    t = [i * 0.01 for i in range(500)]
    sp = [0.0 if i < 100 else 1.0 for i in range(500)]
    y = [0.0 if i < 100 else min(1.3, (i - 100) * 0.02) if i < 200 else 1.0 for i in range(500)]
    ks = key_samples(t, y, sp)
    assert len(ks) <= 20 and any(r[1] == 1.3 for r in ks) and any(abs(r[0] - 1.0) < 1e-9 for r in ks)


def test_risk_tiers_default_deny():
    assert risk.tier("read_telemetry", False) == risk.AUTO
    assert risk.tier("propose_param_change", False) == risk.LOG
    assert risk.tier("flash", True) == risk.HUMAN and risk.tier("erase", False) == risk.HUMAN
    assert risk.tier("run_step_test", False) == risk.HUMAN and risk.tier("run_step_test", True) == risk.LOG
    assert risk.tier("rollback_best", False) == risk.HUMAN and risk.tier("rollback_best", True) == risk.LOG
    for t in ("raw_cmd", "disable_estop", "unlock_rdp", "estop", "something_new"):
        assert risk.tier(t, True) == risk.FORBID


def test_fixed_seed_benchmark_is_reproducible_and_never_violates_bounds():
    a, b = bench.table(seeds=(7,)), bench.table(seeds=(7,))
    assert a == b
    assert all(r["violations"] == 0 for r in a)
    rules = {r["case"]: r for r in a if r["policy"] == "rules" and not r["sim"]}
    assert rules["car_default"]["rounds_to_good"] == 2 and rules["sluggish"]["rounds_to_good"] is not None
    assert all(r["rounds"] <= 8 for r in a if not r["sim"])
    # 假 LLM：一直要求把 kp 拉满 → 护栏把每一步压住，越界 0
    greedy = lambda m, gains, g: '{"action":"PROPOSE","param":"kp","value":2.0}'
    r = bench.run("llm", 7, llm=greedy, start={"kp": 0.03, "ki": 0.3})
    assert r["violations"] == 0 and r["gains"]["kp"] < 2.0
