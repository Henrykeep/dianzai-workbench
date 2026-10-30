"""dzbench/tuning/identify.py（净室实现：Smith 两点法 + SIMC）——用已知参数的模型造数据，验证辨识结果。"""
import math

import pytest

from dzbench.tuning import identify as I


def fopdt(K=2.0, tau=0.5, L=0.1, du=1.0, t_step=0.5, T=4.0, dt=0.01, noise=0.0, y0=0.0):
    t, y, u = [], [], []
    for k in range(int(T / dt)):
        tt = k * dt
        a = tt - t_step - L
        yy = y0 + (K * du * (1 - math.exp(-a / tau)) if a > 0 else 0.0)
        yy += noise * math.sin(k * 2.3) * math.cos(k * 0.7)
        t.append(tt), y.append(yy), u.append(du if tt >= t_step else 0.0)
    return t, y, u


def test_open_loop_recovers_fopdt():
    t, y, u = fopdt()
    r = I.open_loop_pid(t, y, 0.5, 1.0, u)
    assert r["K"] == pytest.approx(2.0, rel=0.03)
    assert r["tau_s"] == pytest.approx(0.5, rel=0.15)
    assert r["dead_s"] == pytest.approx(0.1, abs=0.04)
    # SIMC：τc = max(L, τ/2) = 0.25；Kc = τ/(K(τc+L)) ≈ 0.71
    assert 0.6 < r["pid"]["p"] < 0.85 and r["pid"]["i"] > 0 and r["pid"]["d"] >= 0


def test_open_loop_negative_and_small_units():
    t, y, u = fopdt(K=-0.02, tau=0.3, L=0.05)          # 弧度量纲、反向：原版 0.2 绝对阈值会直接拒绝
    r = I.open_loop_pid(t, y, 0.5, 1.0, u)
    assert r["K"] == pytest.approx(-0.02, rel=0.05)


def test_open_loop_rejects_no_motion():
    t, y, u = fopdt(K=0.0, noise=0.01)
    with pytest.raises(I.IdentError):
        I.open_loop_pid(t, y, 0.5, 1.0, u)


def test_steady_reasons():
    t, y, _ = fopdt(T=4.0)
    assert I.steady_state(t, y, t_step=0.5, span_ref=2.0)["reason"] == "steady"
    t2, y2, _ = fopdt(tau=5.0, T=2.0)                   # 慢：窗口里还在爬
    assert I.steady_state(t2, y2, t_step=0.5, window_s=0.9, span_ref=2.0)["reason"] == "still_drifting"
    assert I.steady_state(t[:5], y[:5])["reason"] == "too_few_samples"
    ys = [0.0] * 50 + [1.0 + 0.5 * math.sin(i * 0.6) for i in range(150)]
    assert I.steady_state(t[:200], ys, t_step=0.5, span_ref=1.0)["reason"] == "oscillating"
    flat = [1.0] * 200
    assert I.steady_state(t[:200], flat, t_step=0.5, span_ref=1.0)["reason"] == "too_little_motion"
    assert I.steady_state(t[:60], y[:60], t_step=0.5, span_ref=2.0)["reason"] == "warming_up"
