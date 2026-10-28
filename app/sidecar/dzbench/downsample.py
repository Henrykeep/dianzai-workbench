"""给 UI 的抽稀：每个 UI 帧（~16 ms）每通道最多 max_points 点；超出时按桶取 min/max，峰值不丢。

做法同 PlotJuggler / Grafana 的 min-max 抽稀（M4 算法的简化版）：比均值抽稀更适合看超调和毛刺。
"""
from __future__ import annotations


def minmax(t: list[float], ys: dict[str, list[float]], max_points: int = 200):
    n = len(t)
    if n <= max_points:
        return t, ys
    buckets = max_points // 2
    out_t: list[float] = []
    out = {k: [] for k in ys}
    for b in range(buckets):
        lo, hi = b * n // buckets, (b + 1) * n // buckets
        if hi <= lo:
            continue
        out_t += [t[lo], t[hi - 1]]
        for k, y in ys.items():
            seg = y[lo:hi]
            i_mn = min(range(len(seg)), key=seg.__getitem__)
            i_mx = max(range(len(seg)), key=seg.__getitem__)
            a, c = (seg[i_mn], seg[i_mx]) if i_mn <= i_mx else (seg[i_mx], seg[i_mn])
            out[k] += [a, c]
    return out_t, out
