"""PSO / 分阶段搜索（PID_Helper 移植）在 FOPDT 仿真上真的变好；PSO 实机门禁；固定种子可复现。"""
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
    assert r["best"]["score"] < 0.95, r["best"]   # PSO 原版边界窄（seed 附近），只要求比初值明显好
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
    from pid_helper_pso import score
    m = simulate_fopdt({"kp": 50, "ki": 50, "kd": 0}, **PLANT, t_end=2.0)
    assert all(math.isfinite(v) for v in m.values())
    assert score(m, ev(SEED)) > 1.0 or m["control_ripple"] > 0.05


def test_bounds_respected():
    bnd = {"kp": (0, 0.5), "ki": (0, 0.3), "kd": (0, 0.01)}
    r = optimize(ev, SEED, strategy="pso", sim=True, iterations=6, swarm=6, bounds=bnd)
    for c in r["top"]:
        assert all(bnd[k][0] <= c["gains"][k] <= bnd[k][1] for k in bnd)
