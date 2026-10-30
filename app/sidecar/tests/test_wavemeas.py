"""上位机波形参数测量（缺口第 7 项）：期望值按解析式手算。"""
import math

from dzbench.wavemeas import measure, measure_window, phase_deg


def test_sine_levels_freq_duty():
    fs = 1000.0
    y = [1.0 + 2.0 * math.sin(2 * math.pi * 12.3 * i / fs) for i in range(2000)]
    r = measure(y, fs)
    assert r["type"] == "正弦"
    assert abs(r["freq"] - 12.3) < 0.05 and abs(r["pp"] - 4.0) < 0.01 and abs(r["avg"] - 1.0) < 0.05
    assert abs(r["rms_ac"] - 2 / math.sqrt(2)) < 0.01 and abs(r["duty"] - 0.5) < 0.01


def test_square_duty_triangle_dc():
    sq = [3.0 if (i % 40) < 10 else 0.0 for i in range(1000)]
    r = measure(sq, 1000.0)
    assert abs(r["freq"] - 25.0) < 0.01 and abs(r["duty"] - 0.25) < 0.005
    assert measure([1.0 if (i % 40) < 20 else 0.0 for i in range(1000)], 1000.0)["type"] == "方波"
    tri = [abs((i % 50) - 25) for i in range(1000)]
    assert measure(tri, 1000.0)["type"] == "三角"
    saw = [float(i % 50) for i in range(1000)]
    assert measure(saw, 1000.0)["type"] == "锯齿"
    d = measure([2.0] * 100, 100.0)
    assert d["type"] == "直流" and d["freq"] is None
    assert not measure([1.0], 100.0)["ok"]


def test_phase_and_window():
    fs, f = 500.0, 7.7
    a = [math.sin(2 * math.pi * f * i / fs) for i in range(1000)]
    b = [0.3 * math.sin(2 * math.pi * f * i / fs + math.radians(30)) for i in range(1000)]
    assert abs(phase_deg(a, b, fs, f) - 30) < 1 and abs(phase_deg(b, a, fs, f) + 30) < 1
    assert phase_deg(a, [0.0] * 1000, fs, f) is None and phase_deg(a, b, fs, 0) is None
    t = [i / fs for i in range(1000)]
    r = measure_window(t, b, None, a)
    assert abs(r["fs"] - fs) < 1e-6 and abs(r["phase_deg"] - 30) < 1.5
