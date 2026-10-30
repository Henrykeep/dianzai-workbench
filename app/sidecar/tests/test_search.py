"""PSO / 分阶段搜索（净室实现）在 FOPDT 仿真上真的变好；PSO 实机门禁；固定种子可复现。"""
import pytest

from dzbench.agent.experiment import GuardError
from dzbench.tuning.search import optimize, simulate_fopdt

PLANT = dict(K=2.0, T=0.3, L=0.05)
SEED = {"kp": 0.3, "ki": 0.1, "kd": 0.0}


def ev(g):
    return simulate_fopdt(g, **PLANT, t_end=3.0)


@pytest.mark.parametrize("strategy", ["pso", "staged"])
def test_search_improves_over_seed(strategy):
    r = optimize(ev, SEED, strategy=strategy, sim=True, iterations=12, swarm=8, rng_seed=1)
    assert r["best"]["score"] < 0.95, r["best"]   
    assert r["best"]["metrics"]["itae"] < r["baseline"]["metrics"]["itae"]
    assert len(r["top"]) == 3 and r["top"][0]["score"] <= r["top"][-1]["score"]


def test_pso_reproducible_and_blocked_on_hardware():
    a = optimize(ev, SEED, strategy="pso", sim=True, iterations=4, swarm=5, rng_seed=7)
    b = optimize(ev, SEED, strategy="pso", sim=True, iterations=4, swarm=5, rng_seed=7)
    assert a["best"] == b["best"]
    with pytest.raises(GuardError):
        optimize(ev, SEED, strategy="pso", sim=False)


def test_unstable_gains_scored_badly_not_crash():
    import math
    from dzbench.tuning.search import score
    m = simulate_fopdt({"kp": 50, "ki": 50, "kd": 0}, **PLANT, t_end=2.0)
    assert all(math.isfinite(v) for v in m.values())
    assert score(m, ev(SEED)) > 1.0 or m["control_ripple"] > 0.05


def test_bounds_respected():
    bnd = {"kp": (0, 0.5), "ki": (0, 0.3), "kd": (0, 0.01)}
    r = optimize(ev, SEED, strategy="pso", sim=True, iterations=6, swarm=6, bounds=bnd)
    for c in r["top"]:
        assert all(bnd[k][0] <= c["gains"][k] <= bnd[k][1] for k in bnd)


def _open_loop(K=2.0, T=0.3, L=0.05, du=0.5, dt=0.005, t_end=3.0):
    t, y, u, x, buf = [], [], [], 0.0, [0.0] * int(L / dt + 1)
    for i in range(int(t_end / dt)):
        tt = i * dt
        uu = du if tt >= 0.5 else 0.0
        buf.append(uu)
        x += dt / T * (K * buf.pop(0) - x)
        t.append(tt); y.append(x); u.append(uu)
    return t, y, u


def test_search_from_step_identifies_and_searches():
    from dzbench.tuning.search import search_from_step
    t, y, u = _open_loop()
    r = search_from_step(t, y, u, strategy="staged", iterations=8)
    assert abs(r["model"]["K"] - 2.0) < 0.3 and r["model"]["seed_from"] == "identify"
    assert r["best"]["score"] <= 1.0 and len(r["top"]) == 3


def test_wide_mode_reaches_further():
    narrow = optimize(ev, SEED, strategy="pso", sim=True, iterations=12, swarm=8, rng_seed=1)
    wide = optimize(ev, SEED, strategy="pso", sim=True, iterations=12, swarm=8, rng_seed=1, wide=True)
    assert wide["wide"] and wide["best"]["score"] <= narrow["best"]["score"] + 1e-9
    st = optimize(ev, SEED, strategy="staged", sim=True, iterations=12, wide=True)
    assert st["best"]["score"] < 0.8



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
