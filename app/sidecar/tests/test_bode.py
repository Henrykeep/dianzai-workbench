import math

from dzbench.agent import bode


def test_measure_pure_sine():
    f, dt = 2.0, 0.002
    t = [k * dt for k in range(3000)]
    u = [math.sin(2 * math.pi * f * x) for x in t]
    y = [0.5 * math.sin(2 * math.pi * f * x - math.pi / 4) + 3 for x in t]
    p = bode.measure(t, u, y, f)
    assert abs(p["gain"] - 0.5) < 1e-3 and abs(p["phase"] + 45) < 0.5 and p["quality"] < 1e-3


def test_first_order_closed_loop_bandwidth_matches_analytic():
    K, tau, kp = 2.0, 0.5, 4.0
    fbw = (1 + kp * K) / tau / (2 * math.pi)          # 闭环 τc = τ/(1+kpK)
    pts = bode.simulate_sweep(K, tau, 0.0, kp, freqs=bode.log_freqs(fbw / 10, fbw * 5, 14), dt=0.0005)
    s = bode.closed_loop_summary(pts)
    assert abs(s["bandwidth_hz"] / fbw - 1) < 0.05, (s, fbw)
    assert s["lag90_hz"] is None                        # 一阶闭环相位只趋近 −90°
    assert not s["unreliable"]


def test_predict_matches_sim_and_margins():
    K, tau, L, kp, ki = 1.0, 1.0, 0.1, 3.0, 2.0
    pr = bode.predict(K, tau, L, kp, ki)
    pts = bode.simulate_sweep(K, tau, L, kp, ki, freqs=bode.log_freqs(0.02, 3, 12), dt=0.001)
    s = bode.closed_loop_summary(pts)
    assert abs(s["bandwidth_hz"] / pr["bandwidth_hz"] - 1) < 0.08, (s["bandwidth_hz"], pr["bandwidth_hz"])
    assert 20 < pr["phase_margin_deg"] < 90 and pr["gain_margin_db"] > 3


def test_unstable_gain_has_negative_margin():
    pr = bode.predict(1.0, 1.0, 0.5, 8.0)
    assert pr["gain_margin_db"] < 0 and pr["phase_margin_deg"] < 0


def test_nonlinear_point_flagged():
    f, dt = 1.0, 0.002
    t = [k * dt for k in range(4000)]
    u = [math.sin(2 * math.pi * f * x) for x in t]
    y = [max(-0.3, min(0.3, v)) for v in u]           # 饱和削顶
    p = bode.measure(t, u, y, f)
    assert p["quality"] > 0.01
    assert bode.closed_loop_summary([dict(p, quality=0.5)])["unreliable"] == [1.0]
