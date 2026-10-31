"""通用自动整定（#78 / #82）：不认题号、不认对象种类，只认工程声明。

输入只有三样：app.yaml 的可调参数声明（名字随意，role ∈ kp/ki/kd/ff/ulim + 范围 + max_delta）、
link.yaml 的物理上限（量程、执行器上限、采样周期）、spec.txt 的一句题面指标。被控对象当黑盒，经 board 接口做阶跃。

流程：小幅闭环探测阶跃 → sysidentpy（BSD-3）辨识 ARX 模型 → python-control（BSD-3）在模型上搜 PID 初值
→ 上板迭代几轮取最好 → 按题面逐条判定；调不到就说清卡在哪（饱和 / 时延过大 / 非最小相位 / 未达标），不装达标。
"""
from __future__ import annotations

import math
import re

import numpy as np

ROLES = ("kp", "ki", "kd", "ff", "ulim")


# ---------------------------------------------------------------- 题面指标抽取
def parse_spec(text: str) -> dict:
    """「稳态误差不超过 2%，超调不超过 10%，调节时间不超过 3 s」→ {ss_err_pct, overshoot_pct, settle_s}；抽不出 = 按默认判定。"""
    t = (text or "").replace("％", "%").replace("≤", "不超过").replace("<=", "不超过").replace("小于", "不超过")
    out: dict = {"raw": text}
    for key, pat in (("ss_err_pct", r"稳态误差[^0-9]{0,6}?([\d.]+)\s*%"), ("overshoot_pct", r"超调量?[^0-9]{0,6}?([\d.]+)\s*%"),
                     ("settle_s", r"(?:调节|稳定|调整)时间[^0-9]{0,6}?([\d.]+)\s*(?:s|秒)")):
        m = re.search(pat, t)
        out[key] = float(m.group(1)) if m else None
    ma = re.search(r"阶跃(?:幅度|幅值|大小)?[为是]?\s*([\d.]+)", t)
    out["amp"] = float(ma.group(1)) if ma else None
    if out["ss_err_pct"] is None and out["amp"]:                 # 绝对误差（带题面单位）→ 相对阶跃幅度的百分比
        m = re.search(r"稳态误差[^0-9]{0,6}?([\d.]+)\s*(?!%)", t)
        if m:
            out["ss_err_pct"] = float(m.group(1)) / out["amp"] * 100
    out["default"] = all(out[k] is None for k in ("ss_err_pct", "overshoot_pct", "settle_s"))
    if out["default"]:
        out["note_zh"] = "按默认判定"
    return out


# ---------------------------------------------------------------- 阶跃指标（与对象无关）
def metrics(t, r, y, amp) -> dict:
    t, y = np.asarray(t, float), np.asarray(y, float)
    a = abs(amp) or 1.0
    s = 1.0 if amp >= 0 else -1.0
    n = len(y)
    tail = y[int(n * 0.85):]
    e = (np.asarray(r, float) - y)
    ss = abs(float(np.mean(tail)) - float(np.asarray(r, float)[-1])) / a * 100
    os_ = max(0.0, float(np.max(s * (y - np.asarray(r, float)[-1]))) / a * 100)
    band = 0.05 * a
    out = np.where(np.abs(e) > band)[0]
    settle = float(t[out[-1] + 1] - t[0]) if len(out) and out[-1] + 1 < n else (0.0 if not len(out) else math.inf)
    dt = float(t[1] - t[0]) if n > 1 else 1.0
    iae = float(np.sum(np.abs(e)) * dt) / a / max(float(t[-1] - t[0]), dt)
    if not np.all(np.isfinite(y)):
        return {"ss_err_pct": math.inf, "overshoot_pct": math.inf, "settle_s": math.inf, "iae": math.inf}
    return {"ss_err_pct": ss, "overshoot_pct": os_, "settle_s": settle, "iae": iae}


def cost(m: dict) -> float:
    if not all(math.isfinite(m[k]) for k in ("ss_err_pct", "overshoot_pct", "iae")):
        return 1e9
    return m["iae"] + 0.004 * m["overshoot_pct"] + 0.01 * m["ss_err_pct"]


def meets(m: dict, sp: dict) -> list[str]:
    """不满足的指标名（空 = 全达标）。"""
    bad = []
    for k in ("ss_err_pct", "overshoot_pct", "settle_s"):
        if sp.get(k) is not None and not (m[k] <= sp[k]):
            bad.append(k)
    return bad


# ---------------------------------------------------------------- 通用离散 PID 闭环（模型和板子都能用）
def pid_loop(step_fn, p: dict, r: np.ndarray, dt: float, u_max: float) -> tuple[np.ndarray, np.ndarray]:
    """step_fn(u) → y（对象推进一拍）。PID 并联式 + 前馈 + 输出限幅（ulim 参数与执行器上限取小）+ 积分抗饱和。"""
    kp, ki, kd, ff = (float(p.get(k, 0.0)) for k in ("kp", "ki", "kd", "ff"))
    lim = min(u_max, float(p["ulim"])) if p.get("ulim") else u_max
    n = len(r)
    y, u = np.zeros(n), np.zeros(n)
    integ, prev_y, yk = 0.0, 0.0, 0.0
    for k in range(n):
        e = r[k] - yk
        d = -(yk - prev_y) / dt if k else 0.0
        v = kp * e + integ + kd * d + ff * r[k]
        uk = min(max(v, -lim), lim)
        if uk == v or (v > lim and e < 0) or (v < -lim and e > 0):
            integ += ki * e * dt
        prev_y = yk
        yk = step_fn(uk)
        if not math.isfinite(yk) or abs(yk) > 1e12:
            y[k:], u[k:] = math.nan, uk
            break
        y[k], u[k] = yk, uk
    return y, u


class LinModel:
    """离散状态空间 + 整数拍时延（python-control 给的 A,B,C,D）。"""

    def __init__(self, sysd, delay_n: int = 0):
        import control
        ss = control.ss(sysd)
        self.A, self.B, self.C, self.D = (np.asarray(m, float) for m in (ss.A, ss.B, ss.C, ss.D))
        self.delay_n = int(delay_n)

    def stepper(self):
        x = np.zeros((self.A.shape[0], 1))
        buf = [0.0] * self.delay_n

        def f(u):
            nonlocal x
            buf.append(u)
            ud = buf.pop(0)
            yk = float((self.C @ x)[0, 0] + self.D[0, 0] * ud)
            x = self.A @ x + self.B * ud
            return yk
        return f


# ---------------------------------------------------------------- 辨识（sysidentpy ARX）
def identify(u: np.ndarray, y: np.ndarray, dt: float, max_lag: int = 4):
    """闭环探测数据 (u, y) → (离散 tf, 拍时延, 信息)。用 sysidentpy FROLS（线性多项式 = ARX）选项。"""
    import control
    from sysidentpy.basis_function import Polynomial
    from sysidentpy.model_structure_selection import FROLS
    from sysidentpy.parameter_estimation import LeastSquares
    ok = np.isfinite(y) & np.isfinite(u)
    u, y = u[ok], y[ok]
    du = np.abs(np.diff(u))
    k0 = int(np.argmax(du > 1e-9 * (np.max(du) + 1e-12))) if len(du) else 0
    resp = np.where(np.abs(y[k0:] - y[k0]) > 0.02 * (np.max(np.abs(y - y[k0])) + 1e-12))[0]
    dn = max(int(resp[0]) - 1, 0) if len(resp) else 0
    dn = min(dn, len(y) // 4)
    xl = list(range(dn + 1, dn + 1 + max_lag))
    m = FROLS(ylag=max_lag, xlag=xl, order_selection=True, info_criteria="aic", n_info_values=2 * max_lag,
              estimator=LeastSquares(), basis_function=Polynomial(degree=1), model_type="NARMAX")
    sc = float(np.std(y) or 1.0)
    m.fit(X=u.reshape(-1, 1), y=(y / sc).reshape(-1, 1))
    a, b = np.zeros(max_lag + 1), np.zeros(max_lag + 1)
    a[0] = 1.0
    for row, th in zip(m.final_model, np.ravel(m.theta)):
        c = int(row[0])
        if 1001 <= c < 2000:
            a[c - 1000] = -th
        elif 2001 <= c < 3000:
            b[c - 2000 - dn] = th * sc
    num, den = b, a
    sysd = control.tf(num, den, dt)
    poles = np.abs(np.roots(den)) if np.count_nonzero(den[1:]) else np.array([0.0])
    return sysd, dn, {"delay_n": dn, "terms": len(m.final_model), "max_pole": float(np.max(poles)) if len(poles) else 0.0}


# ---------------------------------------------------------------- 整定
def _clip(p: dict, decl: list[dict]) -> dict:
    return {d["role"]: float(min(max(p.get(d["role"], d["init"]), d["min"]), d["max"])) for d in decl}


def design(model: LinModel, decl: list[dict], amp: float, dt: float, n: int, u_max: float, rng: np.random.Generator,
           init: dict, tries: int = 160) -> dict:
    """在辨识模型上随机 + 局部搜索 PID（只在声明范围内、只动声明了的参数）。"""
    r = np.full(n, amp)

    def c(p):
        y, _ = pid_loop(model.stepper(), p, r, dt, u_max)
        return cost(metrics(np.arange(n) * dt, r, y, amp))
    best, bc = dict(init), c(init)
    for i in range(tries):
        if i < tries // 2:      # 全局：范围内按对数均匀
            p = {d["role"]: float(math.exp(rng.uniform(math.log(max(d["min"], 1e-9)), math.log(d["max"])))) if d["min"] >= 0 and d["max"] > 0
                 else float(rng.uniform(d["min"], d["max"])) for d in decl}
        else:                   # 局部：在当前最好附近乘性扰动
            p = {k: v * float(math.exp(rng.normal(0, 0.35))) for k, v in best.items()}
        p = _clip(p, decl)
        cc = c(p)
        if cc < bc:
            best, bc = p, cc
    return best


def simc_pid(model: "LinModel", decl: list[dict], dt: float) -> dict | None:
    """辨识模型的阶跃响应 → 一阶加纯滞后（stepident 两点法）→ SIMC（Skogestad）PI/PID 初值，裁进声明范围。积分对象按 K'/s 处理。"""
    from ..agent import stepident
    n = 3000
    f = model.stepper()
    y = [f(1.0) for _ in range(n)]
    t = [i * dt for i in range(n)]
    if not np.all(np.isfinite(y)):
        return None
    tail = np.diff(y[-50:]) / dt
    if abs(float(np.mean(tail))) > 1e-3 * (abs(y[-1]) + 1e-9) / (n * dt) * 10:       # 末段还在线性涨 → 积分对象
        kv = float(np.mean(tail))
        moved = np.where(np.abs(np.asarray(y)) > 1e-6 * (abs(y[-1]) + 1e-12))[0]
        L = max(float(moved[0]) * dt if len(moved) else dt, dt)
        tc = max(L, 3 * dt)
        p = {"kp": 1.0 / (kv * (tc + L)), "ki": 1.0 / (kv * (tc + L)) / (4 * (tc + L)), "kd": 0.0, "ff": 0.0}
    else:
        idn = stepident.identify([-3 * dt, -2 * dt, -dt] + t, [0.0] * 3 + y, 0.0, 1.0)
        if not idn or not idn.get("ok") or not idn["K"]:
            return None
        K, L, T = idn["K"], max(idn["L"], dt), idn["T"]
        tc = L
        kp = T / (K * (tc + L))
        p = {"kp": kp, "ki": kp / min(T, 4 * (tc + L)), "kd": 0.0, "ff": 0.0}
    have = {d["role"] for d in decl}
    if "ki" not in have:
        p["kp"] *= 0.7
    return _clip({k: v for k, v in p.items() if k in have}, decl)


def autotune(board, app: dict, link: dict, spec_text: str, seed: int, rounds: int = 12) -> dict:
    """board：read_params() / write_param(name, v)（受 max_delta，超了拒写）/ step(amp, n) → (t, r, y, u)。"""
    import control  # noqa: F401  python-control：模型仿真 / 设计
    from ..agent import stepident
    rng = np.random.default_rng(seed + 7919)
    decl = [dict(d) for d in app["params"]]
    name = {d["role"]: d["name"] for d in decl}
    sp = parse_spec(spec_text)
    dt = float(link["sample_s"])
    u_max = float(link["u_max"])
    rng_phys = float(link.get("range") or link.get("sensor_range") or 0.0) or None   # 新声明只写物理量程 sensor_range
    max_step = float(link.get("max_step") or 0.0) or None
    cur = board.read_params()
    p0 = {d["role"]: float(cur[d["name"]]) for d in decl}
    for d in decl:
        d["init"] = p0[d["role"]]

    def write(p):
        for d in decl:
            nm, tgt = d["name"], p[d["role"]]
            v = float(board.read_params()[nm])
            md = float(d.get("max_delta") or math.inf)
            while abs(tgt - v) > 1e-12:
                v = v + max(min(tgt - v, md), -md)
                board.write_param(nm, v)

    def run(p, amp, n):
        write(p)
        t, r, y, u = board.step(amp, n)
        return t, r, y, u, metrics(t, r, y, amp)

    # 1) 小幅探测：量程 × PROBE_FRAC，时长先按采样周期给个够长的窗，阶跃时序再由 stepident 实测推出
    lim = rng_phys                                              # #108：探测幅度 = 量程的分数，再受 max_step 夹住；没声明量程走最小可测幅度
    if max_step:
        lim = min(lim, max_step / stepident.PROBE_FRAC) if lim else max_step / stepident.PROBE_FRAC
    probe, _why = stepident.probe_amp(lim)
    n_probe = 600
    p = dict(p0)
    for _ in range(6):                                          # 初值不稳定 → 减半增益直到不跑飞（声明范围内）
        t, r, y, u, m0p = run(p, probe, n_probe)
        if np.all(np.isfinite(y)) and np.max(np.abs(y)) < 50 * probe:
            break
        p = _clip({k: (v * 0.5 if k in ("kp", "ki", "kd") else v) for k, v in p.items()}, decl)
    ts = np.concatenate([[-dt * 3, -dt * 2, -dt], t])
    ys = np.concatenate([[0.0, 0.0, 0.0], np.nan_to_num(y)])
    idn = stepident.identify(list(ts), list(ys), 0.0, probe) if np.all(np.isfinite(y)) else None
    timing = stepident.derive(idn, rng_phys, probe) or {}
    amp = float(timing.get("step_target") or probe * 5)
    if sp.get("amp"):                                           # 题面写了阶跃幅度 → 就按它判（判卷与题面同一个实验）
        amp = float(sp["amp"])
    lims = [x for x in (max_step, (0.5 * rng_phys) if rng_phys else None) if x]
    if lims and abs(amp) > min(lims):
        amp = math.copysign(min(lims), amp)
    settle = (idn["L"] + stepident.SETTLE_TC * idn["T"]) if idn and idn.get("ok") else n_probe * dt / 3
    n = int(min(max(round(3 * settle / dt), 300), 1500))      # 判卷窗口 = 3 × 实测调节时间（按拍数，与墙钟无关）
    if sp.get("settle_s"):                                      # 窗口至少盖住题面调节时间的 2 倍，否则“调节时间”判不了
        n = int(min(max(n, round(2 * float(sp["settle_s"]) / dt)), 20000))

    # 2) 初值（第 0 轮）在正式幅度上的表现
    t, r, y, u, m_init = run(p0, amp, n)
    # 3) sysidentpy 辨识（用探测 + 第 0 轮数据里较好的一段）
    try:
        sysd, dn, info = identify(u, y, dt) if np.all(np.isfinite(y)) else identify(*run(p, probe, n_probe)[3:1:-1], dt)
        model = LinModel(sysd, dn)
    except Exception as e:  # noqa: BLE001
        model, info = None, {"error": str(e)}
    # 4) python-control 模型上搜初值 → 上板迭代
    hist = [(cost(m_init), p0, m_init, (t, r, y, u))]
    cands = [design(model, decl, amp, dt, n, u_max, rng, p0)] if model else []
    simc = simc_pid(model, decl, dt) if model else None
    if simc:
        cands.append(simc)
    for c in cands:
        res = run(c, amp, n)
        hist.append((cost(res[4]), c, res[4], res[:4]))
    steps = [(r_, f) for r_ in (d["role"] for d in decl if d["role"] != "ulim") for f in (1.6, 1 / 1.6)]
    for k in range(rounds):                                   # 上板坐标搜索：每轮挑一个参数 ×/÷，只保留变好的
        best = min(hist, key=lambda h: h[0])
        r_, f = steps[k % len(steps)] if steps else ("kp", 1.0)
        c = _clip(dict(best[1], **{r_: max(best[1][r_], 1e-6 * (next(d for d in decl if d["role"] == r_)["max"] or 1)) * f}), decl)
        res = run(c, amp, n)
        hist.append((cost(res[4]), c, res[4], res[:4]))
    bc, bp, bm, (bt, br, by, bu) = min(hist, key=lambda h: h[0])
    bad = meets(bm, sp)
    if not bad:                                                 # 达标要复现：同参数再跑两次（带噪声），任一次不达标就不算 pass
        for _ in range(2):
            mm = run(bp, amp, n)[4]
            if meets(mm, sp):
                bad = meets(mm, sp)
                break
    # 5) 诚实判定：卡在哪
    lim = min(u_max, bp.get("ulim", math.inf))
    sat = float(np.mean(np.abs(bu[: max(len(bu) // 2, 1)]) >= 0.98 * lim))
    sgn = 1.0 if amp >= 0 else -1.0
    rise = np.where(sgn * by >= 0.1 * abs(amp))[0]                 # 只看第一次到 10% 之前：起步反向 = 非最小相位
    inv = float(np.min(sgn * by[: (int(rise[0]) if len(rise) else len(by)) + 1])) / abs(amp)
    LT = (idn["L"] / idn["T"]) if idn and idn.get("ok") and idn.get("T") else 0.0
    if not bad:
        verdict, why = "pass", "各项指标实测满足题面"
        cat = None
    else:
        verdict = "fail"
        Kst = abs(float(idn["K"])) if idn and idn.get("ok") and idn.get("K") is not None else None
        settled = bool(idn and idn.get("ok") and (idn["L"] + 3 * idn["T"]) < 0.7 * n_probe * dt)   # 探测窗里走稳了，K 才可信
        reach = (Kst * lim / abs(amp)) if Kst and settled else None             # 满输出的稳态能走到目标的几成（积分对象不看）
        if inv < -0.03:
            cat, why = "nonminimum_phase", f"起步先反向 {abs(inv) * 100:.1f}%：非最小相位，快了必反冲"
        elif reach is not None and reach < 0.98 and not (idn or {}).get("integrating"):
            cat, why = "saturation", f"满输出稳态只能到目标的 {reach * 100:.0f}%：执行器饱和"
        elif LT > 0.8:
            cat, why = "delay", f"纯滞后 / 时间常数 ≈ {LT:.2f}：时延过大"
        elif sat > 0.3:
            cat, why = "saturation", f"执行器 {sat * 100:.0f}% 时间顶在上限：饱和，再加增益也快不了"
        else:
            cat, why = "not_reached", "模型与板上都没搜到满足题面的参数"
        why += "；未达标：" + "、".join(bad)
    return {"seed": seed, "verdict": verdict, "category": cat, "pass_basis": why, "spec": sp, "amp": amp, "n": n,
            "timing": timing, "ident": info, "initial": {"params": {name[k]: v for k, v in p0.items()}, "metrics": m_init, "cost": cost(m_init)},
            "best": {"params": {name[k]: v for k, v in bp.items()}, "roles": bp, "metrics": bm, "cost": bc},
            "rounds": len(hist) - 1}
