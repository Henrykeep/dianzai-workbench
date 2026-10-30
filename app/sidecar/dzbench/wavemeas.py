"""波形参数测量（上位机侧，作用在遥测曲线上）：与固件 firmware/algo/wavemeas 同一算法。
最小/最大/峰峰/均值/交流有效值、频率/周期（中点 ±10% 施密特过零 + 线性插值）、占空比（整周期内高于中点的比例）、
波形类型（只用时域规则：峰值因数² + 贴轨比例 + 锯齿跳变，阈值同原版）、两路相位差（已知频率单频 DFT + Hann）。
Source: LP-MSPM0G3507_freertos_firework@ede35a2 application/waveform/waveform_measurement/waveform_measurement.c
（MIT，阡陌）的时域特征与分类阈值；Python 改写。
"""
from __future__ import annotations

import cmath
import math
import statistics

TYPES = {0: "未知", 1: "直流", 2: "正弦", 3: "方波", 4: "三角", 5: "锯齿", 6: "谐波"}


def _classify(y: list[float]) -> int:
    n = len(y)
    lo, hi = min(y), max(y)
    pp = hi - lo
    if pp <= 1e-12 * max(1.0, abs(hi)):
        return 1
    avg = sum(y) / n
    dev = [abs(v - avg) for v in y]
    ss = sum(d * d for d in dev)
    if ss == 0:
        return 1
    crest2 = max(dev) ** 2 * n / ss
    lo_r = sum(v <= lo + 0.1 * pp for v in y) / n
    hi_r = sum(v >= hi - 0.1 * pp for v in y) / n
    steps = [abs(b - a) for a, b in zip(y, y[1:])]
    if crest2 <= 1.35 and lo_r + hi_r >= 0.7 and lo_r >= 0.05 and hi_r >= 0.05:
        return 3
    if 2.45 < crest2 <= 4.0 and sum(steps) > 0 and max(steps) * (n - 1) > sum(steps) * 4:
        return 5
    if 1.35 < crest2 <= 2.7 and lo_r + hi_r >= 0.3 and lo_r >= 0.05 and hi_r >= 0.05:
        return 2
    if 1.4 <= crest2 <= 2.45:
        return 2
    return 4 if crest2 <= 4.0 else 6


def measure(y: list[float], fs: float) -> dict:
    if len(y) < 8 or not fs > 0:
        return {"ok": False, "reason": "数据太少（至少 8 个点）或采样率未知"}
    n = len(y)
    lo, hi = min(y), max(y)
    pp = hi - lo
    avg = sum(y) / n
    r = {"ok": True, "n": n, "fs": fs, "min": lo, "max": hi, "pp": pp, "avg": avg,
         "rms_ac": math.sqrt(sum((v - avg) ** 2 for v in y) / n), "freq": None, "period": None,
         "duty": None, "edges": 0}
    r["type"] = TYPES[_classify(y)]
    if pp <= 0:
        return r
    mid, hy = lo + pp / 2, pp * 0.1
    high = y[0] > mid
    rises: list[tuple[float, int]] = []
    for i in range(1, n):
        if not high and y[i] >= mid + hy:
            high = True
            j = i
            while j > 0 and y[j - 1] >= mid:
                j -= 1
            t = float(j)
            if j > 0 and y[j] != y[j - 1]:
                t = (j - 1) + (mid - y[j - 1]) / (y[j] - y[j - 1])
            rises.append((t, j))
        elif high and y[i] <= mid - hy:
            high = False
    r["edges"] = len(rises)
    if len(rises) >= 2:
        (t0, i0), (t1, i1) = rises[0], rises[-1]
        r["period"] = (t1 - t0) / (len(rises) - 1) / fs
        r["freq"] = 1 / r["period"]
        r["duty"] = sum(v >= mid for v in y[i0:i1]) / (i1 - i0)
    else:
        r["duty"] = sum(v >= mid for v in y) / n
    return r


def phase_deg(a: list[float], b: list[float], fs: float, freq: float) -> float | None:
    """b 相对 a 的相位差（度，(-180, 180]，正 = b 超前）。两路须同批采样、等长。"""
    n = min(len(a), len(b))
    if n < 8 or not fs > 0 or not freq or not 0 < freq < fs / 2:
        return None
    w = 2 * math.pi * freq / fs

    def dft(x):
        x = x[-n:]
        m = sum(x) / n
        return sum((v - m) * (0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1))) * cmath.exp(-1j * w * i)
                   for i, v in enumerate(x))
    A, B = dft(a), dft(b)
    if abs(A) < 1e-9 or abs(B) < 1e-9:
        return None
    d = math.degrees(cmath.phase(B * A.conjugate()))
    return d + 360 if d <= -180 else d


def measure_window(t: list[float], y: list[float], period_s: float | None = None,
                   ref: list[float] | None = None) -> dict:
    """遥测窗口：采样率取固件周期（没有就用时间戳中位间隔）；ref 给出时算 y 相对 ref 的相位差。"""
    dts = [b - a for a, b in zip(t, t[1:]) if b > a]
    dt = period_s or (statistics.median(dts) if dts else 0)
    r = measure(y, 1 / dt if dt else 0)
    if r.get("ok") and ref is not None and r["freq"]:
        r["phase_deg"] = phase_deg(ref, y, r["fs"], r["freq"])
    return r
