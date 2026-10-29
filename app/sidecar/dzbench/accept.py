"""验收判定：界面 app/ui/src/accept.ts 的同一定义（逐行对应；两边测试共用 tests/accept_vectors.json）。

到位 = |e| ≤ band 且 |v| ≤ vmax，连续保持 hold_s；设定值每变一次开一段（窗口内没变 = 一段保持任务）。
到位时刻 = 保持满 hold_s 那一刻（从该段起点计）；到位后最大误差 = 进入时刻到段末的 max|e|。
通过 = 每段到位 且 到位后误差 ≤ band 且（有 t_max_s 时）第一段起点到最后一段到位 ≤ t_max_s。速度 = 100 ms 窗口差分。
"""
from __future__ import annotations
import math

V_WIN = 0.1


def accept_eval(t: list, y: list, sp: list, a: dict) -> dict | None:
    n = min(len(t), len(y), len(sp))
    if n < 2:
        return None
    band = float(a["band"]); hold = float(a.get("hold_s", 0.3)); vmax = float(a.get("vmax", math.inf)); tol = band * 1e-3
    ch = lambda k: k >= 1 and abs(sp[k] - sp[k - 1]) > tol
    starts = [0] + [k for k in range(1, n) if ch(k) and not ch(k - 1)]
    if len(starts) > 1:
        starts.pop(0)

    def v(k):
        j = k
        while j > 0 and t[k] - t[j - 1] <= V_WIN + 1e-9:
            j -= 1
        return 0.0 if j == k else (y[k] - y[j]) / (t[k] - t[j])

    segs = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else n
        entry = arrive = -1
        for k in range(s, e):
            if not (abs(y[k] - sp[k]) <= band and abs(v(k)) <= vmax):
                entry = -1
                continue
            if entry < 0:
                entry = k
            if t[k] - t[entry] >= hold - 1e-9:
                arrive = k
                break
        err = max(abs(y[k] - sp[k]) for k in range(entry, e)) if arrive >= 0 else math.nan
        segs.append({"t0": t[s], "target": sp[e - 1], "arrived": arrive >= 0,
                     "t_arrive": t[arrive] - t[s] if arrive >= 0 else math.nan, "err_after": err})
    all_in = all(s["arrived"] for s in segs)
    total = segs[-1]["t0"] + segs[-1]["t_arrive"] - segs[0]["t0"] if all_in else math.nan
    worst = max(s["err_after"] for s in segs) if all_in else math.nan
    bad = next((i for i, s in enumerate(segs) if not s["arrived"]), -1)
    why = (f"第 {bad + 1} 段（→{segs[bad]['target']:.4g}）没到位" if bad >= 0 else
           f"到位后误差 {worst:.3g} 超出 ±{band:g}" if worst > band else
           f"用时 {total:.2f} s 超过 {a['t_max_s']} s" if a.get("t_max_s") is not None and total > float(a["t_max_s"]) else "")
    return {"pass": not why, "segs": segs, "total": total, "worst_err": worst, "why": why}
