"""频率响应：正弦扫频测量（锁相 / 单频 DFT）+ 闭环带宽、谐振峰；以及模型预测（FOPDT + PID 的开/闭环 Bode、相位/幅值裕度）。

用途：
  * 测量：仿真板（或真板）给设定值叠加正弦 u，读输出 y；每个频点取整数个周期做单频 DFT，得到增益/相位。
    整数周期 + 去掉开头 settle 周期 → 无泄漏、不需要窗；quality = 拟合残差占比，>0.3 说明非线性/饱和/噪声大，该点不可信。
  * 计算器：已知辨识出的 FOPDT（K、τ、L）和 PID 增益，直接算开环裕度和闭环带宽（不碰板子）。
带宽定义：闭环 |T(jω)| 第一次跌到低频增益的 −3 dB（对数插值）。
参考：Åström & Murray《Feedback Systems》第 9–11 章；锁相测量即单频 Goertzel/DFT。纯 Python。
【仿真】与一阶闭环解析解对过（tests/test_bode.py）。【未测】真板扫频（固件还没有“设定值叠加正弦”的通道）。
"""
from __future__ import annotations

import cmath
import math


def log_freqs(f0: float, f1: float, n: int) -> list[float]:
    if n < 2:
        return [f0]
    r = (f1 / f0) ** (1 / (n - 1))
    return [f0 * r ** i for i in range(n)]


def _tone(t, x, f):
    """x 在频率 f 的复幅值（x ≈ Re(X·e^{jωt}) + 直流），以及正弦+直流拟合后的残差占比。"""
    n = len(t)
    w = 2 * math.pi * f
    m = sum(x) / n
    c = sum((xi - m) * math.cos(w * ti) for ti, xi in zip(t, x)) * 2 / n
    s = sum((xi - m) * math.sin(w * ti) for ti, xi in zip(t, x)) * 2 / n
    X = complex(c, -s)
    res = sum((xi - m - (X * cmath.exp(1j * w * ti)).real) ** 2 for ti, xi in zip(t, x))
    tot = sum((xi - m) ** 2 for xi in x) or 1e-30
    return X, res / tot


def measure(t: list[float], u: list[float], y: list[float], f: float, settle_cycles: float = 2.0) -> dict:
    """单频点：丢掉开头 settle_cycles 个周期，再截成整数个周期。"""
    if len(t) < 8:
        raise ValueError("samples")
    T = 1.0 / f
    t0 = t[0] + settle_cycles * T
    cycles = math.floor((t[-1] - t0) / T)
    if cycles < 1:
        raise ValueError(f"数据太短：{f:g} Hz 需要至少 {settle_cycles + 1:g} 个周期")
    t1 = t0 + cycles * T
    idx = [i for i, ti in enumerate(t) if t0 <= ti < t1]
    tt, uu, yy = [t[i] for i in idx], [u[i] for i in idx], [y[i] for i in idx]
    U, qu = _tone(tt, uu, f)
    Y, qy = _tone(tt, yy, f)
    if abs(U) < 1e-12:
        raise ValueError("输入没有这个频率的分量")
    H = Y / U
    return {"f": f, "gain": abs(H), "db": 20 * math.log10(max(abs(H), 1e-12)),
            "phase": math.degrees(cmath.phase(H)), "quality": max(qu, qy), "cycles": cycles}


def unwrap(points: list[dict]) -> list[dict]:
    prev = None
    for p in points:
        if prev is not None:
            while p["phase"] - prev > 180:
                p["phase"] -= 360
            while p["phase"] - prev < -180:
                p["phase"] += 360
        prev = p["phase"]
    return points


def _cross(points, key, level, falling=True):
    for a, b in zip(points, points[1:]):
        ya, yb = a[key], b[key]
        if (ya >= level > yb) if falling else (ya <= level < yb):
            k = (level - ya) / (yb - ya)
            return math.exp(math.log(a["f"]) + k * (math.log(b["f"]) - math.log(a["f"])))
    return None


def closed_loop_summary(points: list[dict]) -> dict:
    """闭环 Bode → 带宽（−3 dB）、谐振峰 Mr、相位滞后 90° 的频率。点按频率升序。"""
    pts = unwrap(sorted(points, key=lambda p: p["f"]))
    ref = pts[0]["db"]
    rel = [dict(p, rel=p["db"] - ref) for p in pts]
    peak = max(rel, key=lambda p: p["rel"])
    return {"bandwidth_hz": _cross(rel, "rel", -3.0), "dc_db": ref,
            "peak_db": max(0.0, peak["rel"]), "peak_hz": peak["f"] if peak["rel"] > 0.1 else None,
            "lag90_hz": _cross(rel, "phase", -90.0),
            "unreliable": [p["f"] for p in pts if p.get("quality", 0) > 0.3]}


# ---------------- 计算器：FOPDT + PID ----------------

def loop_tf(K, tau, L, kp, ki=0.0, kd=0.0, tf=0.0):
    """开环 L(jω) = C(jω)·G(jω)；C = kp + ki/s + kd·s/(tf·s+1)，G = K·e^{−Ls}/(τs+1)。"""
    def Lw(w):
        s = 1j * w
        C = kp + (ki / s if ki else 0) + (kd * s / (tf * s + 1) if kd else 0)
        return C * K * cmath.exp(-L * s) / (tau * s + 1)
    return Lw


def predict(K, tau, L, kp, ki=0.0, kd=0.0, tf=0.0, f0=None, f1=None, n=200) -> dict:
    """返回开环裕度与闭环带宽（模型预测，未测）。"""
    Lw = loop_tf(K, tau, L, kp, ki, kd, tf)
    f0 = f0 or 0.001 / max(tau, L, 1e-3)
    f1 = f1 or 100.0 / max(min(tau, L) if L > 0 else tau, 1e-3)
    fs = log_freqs(f0, f1, n)
    ol, cl = [], []
    for f in fs:
        l = Lw(2 * math.pi * f)
        T = l / (1 + l)
        ol.append({"f": f, "db": 20 * math.log10(max(abs(l), 1e-12)), "phase": math.degrees(cmath.phase(l))})
        cl.append({"f": f, "db": 20 * math.log10(max(abs(T), 1e-12)), "phase": math.degrees(cmath.phase(T)), "quality": 0.0})
    unwrap(ol)
    fc = _cross(ol, "db", 0.0)
    pm = None
    if fc:
        pm = 180 + math.degrees(cmath.phase(Lw(2 * math.pi * fc)))
        pm = (pm + 180) % 360 - 180
    f180 = _cross(ol, "phase", -180.0)
    gm = -20 * math.log10(abs(Lw(2 * math.pi * f180))) if f180 else None
    s = closed_loop_summary(cl)
    return {"crossover_hz": fc, "phase_margin_deg": pm, "gain_margin_db": gm, "phase180_hz": f180,
            "bandwidth_hz": s["bandwidth_hz"], "peak_db": s["peak_db"], "peak_hz": s["peak_hz"],
            "open_loop": ol, "closed_loop": cl}


# ---------------- 仿真：闭环正弦扫频（测试 / 离线演示） ----------------

def simulate_sweep(K, tau, L, kp, ki=0.0, freqs=(0.1,), amp=1.0, dt=0.001, settle_cycles=2, cycles=4):
    """离散仿真 PI + FOPDT 闭环，设定值 = amp·sin(ωt)，逐频点测 y/sp。"""
    out = []
    nd = max(0, int(round(L / dt)))
    for f in freqs:
        T = 1.0 / f
        n = int((settle_cycles + cycles) * T / dt) + 1
        y = integ = 0.0
        buf = [0.0] * (nd + 1)
        ts, us, ys = [], [], []
        for k in range(n):
            t = k * dt
            sp = amp * math.sin(2 * math.pi * f * t)
            e = sp - y
            integ += ki * e * dt
            u = kp * e + integ
            buf.append(u)
            ud = buf.pop(0)
            y += dt * (K * ud - y) / tau
            ts.append(t); us.append(sp); ys.append(y)
        out.append(measure(ts, us, ys, f, settle_cycles))
    return out
