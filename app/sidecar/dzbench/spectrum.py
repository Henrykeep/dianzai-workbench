"""频谱：遥测按板端固定周期采样（schema 的 telemetry.period_ms），去直流 + Hann 窗 + 实数 FFT。
不依赖 numpy（打包小）；N ≤ 4096 时纯 Python 基 2 FFT 足够快（几十 ms）。
幅值已做窗修正（单边，正弦幅值 A 的峰值≈A）。参考：Harris 1978 “On the Use of Windows…”；Lyons《数字信号处理》。
"""
from __future__ import annotations

import cmath
import math
import statistics


def _fft(x: list[complex]) -> list[complex]:
    n = len(x)
    j = 0
    for i in range(1, n):                       # 位反转
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            x[i], x[j] = x[j], x[i]
    size = 2
    while size <= n:
        w = cmath.exp(-2j * math.pi / size)
        for s in range(0, n, size):
            wk = 1
            for k in range(size // 2):
                a, b = x[s + k], x[s + k + size // 2] * wk
                x[s + k], x[s + k + size // 2] = a + b, a - b
                wk *= w
        size <<= 1
    return x


def spectrum(t: list[float], y: list[float], period_s: float | None = None, max_n: int = 4096) -> dict:
    """返回 {fs, n, df, f, amp, peaks, warn}。t 单位秒。"""
    if len(y) < 16:
        return {"ok": False, "reason": "数据太少（至少 16 个点）：先让曲线跑一会儿"}
    dts = [b - a for a, b in zip(t, t[1:]) if b > a]
    med = statistics.median(dts) if dts else 0.0
    dt = period_s or med
    warn = ""
    if period_s and med and abs(med - period_s) > 0.2 * period_s:
        warn = f"实测采样间隔 {med * 1000:.1f} ms 与固件周期 {period_s * 1000:.1f} ms 不符：可能丢帧或波特率不够，频率轴可能不准"
    gaps = sum(1 for d in dts if d > 1.5 * dt)
    if gaps and not warn:
        warn = f"有 {gaps} 处丢帧（间隔 > 1.5 个周期），频谱会被抹平"
    n = 1 << min(int(math.log2(len(y))), int(math.log2(max_n)))
    seg = y[-n:]
    mean = sum(seg) / n
    w = [0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)) for i in range(n)]
    X = _fft([complex((v - mean) * wi) for v, wi in zip(seg, w)])
    scale = 2.0 / sum(w)
    amp = [abs(X[k]) * scale for k in range(n // 2 + 1)]
    amp[0] = 0.0                                # 已去直流
    fs = 1.0 / dt
    df = fs / n
    f = [k * df for k in range(n // 2 + 1)]
    pk = sorted((k for k in range(1, len(amp) - 1) if amp[k] >= amp[k - 1] and amp[k] >= amp[k + 1]),
                key=lambda k: -amp[k])[:3]
    top = max(amp) or 1.0
    peaks = [{"f": round(f[k], 4), "amp": amp[k]} for k in pk if amp[k] > 0.05 * top]
    return {"ok": True, "fs": fs, "n": n, "df": df, "f": f, "amp": amp, "peaks": peaks, "warn": warn,
            "seconds": n * dt}
