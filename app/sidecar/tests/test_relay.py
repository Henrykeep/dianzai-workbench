"""继电器自整定：FOPDT 对象上 Ku/Pu 与理论描述函数结果对比，噪声带防抖，未收敛报原因。"""
import math

from dzbench.agent.relay import analyze, gains, simulate_fopdt


def theory(K, tau, L):
    # 相位 −π：atan(w·tau) + w·L = π；Ku = sqrt(1+(w·tau)^2)/K
    lo, hi = 1e-3, 1e4
    for _ in range(200):
        w = (lo + hi) / 2
        lo, hi = (w, hi) if math.atan(w * tau) + w * L < math.pi else (lo, w)
    return math.sqrt(1 + (w * tau) ** 2) / K, 2 * math.pi / w


def test_fopdt_matches_theory_within_describing_function_error():
    K, tau, L, d = 2.0, 0.5, 0.1, 0.2
    t, y = simulate_fopdt(K, tau, L, d, T=10)
    r = analyze(t, y, d)
    Ku, Pu = theory(K, tau, L)
    assert r["ok"], r
    assert abs(r["Pu"] - Pu) / Pu < 0.25 and abs(r["Ku"] - Ku) / Ku < 0.35   # 描述函数法本身是近似
    g = gains(r["Ku"], r["Pu"])
    assert g["kp"] > 0 and g["ki"] > 0 and g["kp"] < gains(r["Ku"], r["Pu"], "zn")["kp"]


def test_noise_band_and_not_converged():
    t, y = simulate_fopdt(2.0, 0.5, 0.1, 0.2, band=0.03, noise=0.005, T=10)
    r = analyze(t, y, 0.2, sp=1.0, band=0.03, tol=0.15)
    assert r["ok"], r
    t, y = simulate_fopdt(2.0, 0.5, 0.1, 0.2, T=0.3)
    r = analyze(t, y, 0.2)
    assert not r["ok"] and "峰太少" in r["reason"]
