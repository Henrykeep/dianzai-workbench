"""继电自整定：FOPDT 上 Ku/Pu 与描述函数理论值吻合，给出的 PID 闭环稳定。"""
import math

from dzbench.tuning import relay, search


def _theory(K, T, L):
    # 相位 -π：atan(wT) + wL = π
    lo, hi = 1e-6, math.pi / L
    for _ in range(200):
        w = (lo + hi) / 2
        lo, hi = (w, hi) if math.atan(w * T) + w * L < math.pi else (lo, w)
    return math.sqrt(1 + (w * T) ** 2) / K, 2 * math.pi / w


def test_relay_matches_theory_and_closes_loop():
    K, T, L = 2.0, 1.0, 0.2
    r = relay.relay_sim(K, T, L)
    assert r["ok"], r.get("why")
    ku, pu = _theory(K, T, L)
    assert abs(r["ku"] - ku) / ku < 0.25
    assert abs(r["pu"] - pu) / pu < 0.2
    m = search.simulate_fopdt(r["gains"], K, T, L, u_lim=10.0)
    assert m["steady_error"] < 0.05 and m["overshoot"] < 0.8


def test_relay_reports_no_oscillation():
    r = relay.relay_run(lambda u: 0.0, dt=0.01, step=1.0, noise_band=0.1, t_max=2.0)
    assert not r["ok"] and "没收敛" in r["why"]


def test_tl_rule_is_more_conservative_than_zn():
    r = relay.relay_sim(2.0, 1.0, 0.2)
    zn = search.simulate_fopdt(relay.gains(r["ku"], r["pu"], "zn"), 2.0, 1.0, 0.2, u_lim=10.0)
    tl = search.simulate_fopdt(relay.gains(r["ku"], r["pu"]), 2.0, 1.0, 0.2, u_lim=10.0)
    assert tl["overshoot"] < zn["overshoot"] and tl["steady_error"] < 0.05
