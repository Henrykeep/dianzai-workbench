"""experiment.py：相对基线打分、稳态原因码、四段实验切分、分阶段搜索、门禁（纯离线）。"""
import pytest

from dzbench.agent import bench as B
from dzbench.agent import experiment as E
from dzbench.agent.guard import GuardError, TuneGuard
from dzbench.agent.tuning import step_metrics


def m_of(kp, ki, seed=7):
    return step_metrics(*B.plant_step(kp, ki, seed))


def test_rel_score_baseline_is_one_and_units_free():
    base = m_of(0.08, 1.5)
    assert E.rel_score(base, base) == pytest.approx(1.0)
    worse = m_of(0.6, 15.0)
    for w in E.WEIGHTS:
        assert E.rel_score(worse, base, w) > 1.0
    assert E.rel_score(worse, base, "conservative") > E.rel_score(worse, base, "balanced")   # 怕超调的模板罚得更重


def test_four_segment_plan_and_cut():
    plan = E.four_segment_plan(1.0, 0.5, 1.0)
    assert [v for _, v in plan] == [1.0, 0.5, 1.0, 1.5, 1.0]
    t, y, sp, yv = [], [], [], 1.0
    for k in range(500):
        tt = k * 0.01
        r = next(v for s, v in reversed(plan) if tt >= s)
        yv += (r - yv) * 0.08
        t.append(tt); sp.append(r); y.append(yv)
    segs = E.four_segment_metrics(t, y, sp, plan)
    assert [s["dir"] for s in segs] == ["down", "up", "up", "down"] and all(s["ok"] for s in segs)
    assert E.asymmetry(segs)["asymmetric"] is False


def test_staged_search_goes_p_then_i_and_respects_guard():
    g = TuneGuard({"kp": (0, 2), "ki": (0, 20)}, sim=False)
    s, gains = E.StagedSearch(), {"kp": 0.03, "ki": 0.3}
    m = m_of(**gains)
    g.record(m, gains)
    p, v = s.propose(m, gains, g)
    assert p == "kp" and v <= 0.03 * 1.5 + 1e-9                # 实机档 ×1.5 上限
    r = B.run("staged", 7, sim=False, start={"kp": 0.03, "ki": 0.3})
    assert r["rounds_to_good"] and r["violations"] == 0


def test_gates():
    with pytest.raises(GuardError):
        E.require_open_loop({}, sim=True)
    with pytest.raises(GuardError):
        E.require_open_loop({"plant_stable": True}, sim=False)
    E.require_open_loop({"plant_stable": True, "open_loop_max": 0.2}, sim=False)
    with pytest.raises(GuardError):
        E.require_swarm(sim=False)
    E.require_swarm(sim=True)


def test_slow_unsettled_is_not_unstable():
    from dzbench.agent.guard import stable
    assert stable(m_of(0.039, 0.3))


def test_risk_swarm_sim_only():
    from dzbench.agent import risk
    assert risk.tier("swarm_search", sim=False) == "forbid" and risk.tier("swarm_search", sim=True) == "log"
    assert risk.tier("open_loop_test", sim=False) == "human"


def test_evals_schema_and_grader():
    from dzbench.agent import evals
    from dzbench.agent.loop import SYSTEM
    cs = evals.load()
    assert len({c["id"] for c in cs}) == len(cs) >= 8
    assert "【推断】" in SYSTEM and "待实板确认" in SYSTEM
    c = next(c for c in cs if c["id"] == "edit_reads_first")
    assert evals.grade(c, {"calls": [{"tool": "read_file", "args": {}}, {"tool": "propose_edit", "args": {}}]})[0]
    assert not evals.grade(c, {"calls": [{"tool": "propose_edit", "args": {}}]})[0]
    c = next(c for c in cs if c["id"] == "one_gain_per_round")
    two = [{"tool": "propose_param_change", "args": {"name": n}} for n in ("kp", "ki")]
    assert not evals.grade(c, {"calls": two})[0]
