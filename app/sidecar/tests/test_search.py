"""search.py：原 GPL 搜索删除后 optimize 诚实报不可用；门禁照旧；仿真对象照旧。"""
import math

import pytest

from dzbench.agent.experiment import GuardError
from dzbench.tuning.search import SearchUnavailable, optimize, search_from_step, simulate_fopdt

PLANT = dict(K=2.0, T=0.3, L=0.05)
SEED = {"kp": 0.3, "ki": 0.1, "kd": 0.0}


def ev(g):
    return simulate_fopdt(g, **PLANT, t_end=3.0)


def test_optimize_unavailable_but_guard_first():
    with pytest.raises(GuardError):
        optimize(ev, SEED, strategy="pso", sim=False)
    for st in ("pso", "staged"):
        with pytest.raises(SearchUnavailable, match="暂不可用"):
            optimize(ev, SEED, strategy=st, sim=True)


def test_simulate_unstable_finite():
    m = simulate_fopdt({"kp": 50, "ki": 50, "kd": 0}, **PLANT, t_end=2.0)
    assert all(math.isfinite(v) for v in m.values())


def test_search_from_step_reports_ident_unavailable():
    t = [i * 0.01 for i in range(100)]
    u = [0.0] * 50 + [1.0] * 50
    with pytest.raises(ValueError, match="暂不可用"):
        search_from_step(t, list(u), u)


def test_verify_group_runs_step_only_when_all_accepted():
    """上板验证：整组提议都采纳才触发验证阶跃；有一张拒绝 → 整组作废。"""
    from dzbench.agent.service import AgentService

    class T:
        n = 0
        def propose_param_change(self, k, v, reason, src):
            T.n += 1
            return {"id": T.n, "status": "pending_user_confirmation"}
    svc = AgentService.__new__(AgentService)
    svc.tools = T()
    ids = [r["id"] for r in svc.propose_hint({"kp": 1, "ki": 2}, "x", verify_step=True)]
    assert not svc.verify_after_decide(ids[0], {"status": "applied"})
    assert svc.verify_after_decide(ids[1], {"status": "applied"})
    ids = [r["id"] for r in svc.propose_hint({"kp": 1, "ki": 2}, "x", verify_step=True)]
    assert not svc.verify_after_decide(ids[0], {"status": "rejected"})
    assert not svc.verify_after_decide(ids[1], {"status": "applied"})
    assert not svc.verify_after_decide(99, {"status": "applied"})        # 普通提议不触发
    assert svc.propose_hint({"kp": 1}, "x") and not svc.verify_after_decide(T.n, {"status": "applied"})
