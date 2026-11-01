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


from .steplimit import step_block  # noqa: E402

AMP_WARN_ZH = "按降幅测试，未验题面幅度"


F32_EPS = 2.0 ** -23
DELTA_MARGIN = 1e-6                                              # #126：每步只走 max_delta×(1−1e-6)，避开 float32 舍入后“正好超一点”


def _step_cap(md: float, a: float, b: float) -> float:
    """单步上限：max_delta 留相对余量，再扣掉两端 float32 舍入（板上按 f32 比较）。"""
    return max(md * (1 - DELTA_MARGIN) - 4 * F32_EPS * max(abs(a), abs(b), md), md * 0.5)


def write_one(board, nm: str, tgt: float, max_delta=None, tries: int = 8) -> float:
    """把参数 nm 分步写到 tgt：每步 ≤ max_delta（留余量）；被拒（单步超限）就把这一步缩半重试，不抛错中断整轮整定。
    board.write_param 可以抛异常或返回 {ok:False, reason:"step"}；别的拒绝原因照常抛出。"""
    v = float(board.read_params()[nm])
    md = float(max_delta) if max_delta else math.inf
    while abs(tgt - v) > 1e-12 * max(1.0, abs(tgt)):
        cap = _step_cap(md, v, tgt) if math.isfinite(md) else math.inf
        for _ in range(tries):
            nv = v + max(min(tgt - v, cap), -cap)
            try:
                r = board.write_param(nm, nv)
            except Exception as e:  # noqa: BLE001
                if not _is_step_reject(e) or not math.isfinite(md):
                    raise
                cap *= 0.5
                continue
            if isinstance(r, dict) and r.get("ok") is False:
                if r.get("reason") != "step":
                    raise RuntimeError(f"写 {nm}={nv:g} 被拒：{r.get('reason_zh') or r.get('reason')}")
                cap *= 0.5
                continue
            v = float(board.read_params().get(nm, nv))
            break
        else:
            raise RuntimeError(f"写 {nm} 连续 {tries} 次被单步限幅拒绝（max_delta {md:g}）")
    return v


def _is_step_reject(e) -> bool:
    ex = getattr(e, "extra", None) or {}
    return getattr(e, "code", None) == "invalid_param" and (ex.get("reject") == "step" or ex.get("reason") == "step")

# ---------------------------------------------------------------- 整定策略：代价对齐题面 / 增益下限 / 收敛停 / 按证据诊断
BUDGET_BASE, BUDGET_PER_PARAM, BUDGET_MAX = 12, 6, 48         # 板上试参次数上限随可调参数个数自适应
FAC0, FAC_MIN, IMPROVE_REL = 1.6, 1.05, 0.01
KEPT_INITIAL_ZH = "调参未能改善，已保留初值"
# 配对比较不确定（改善没超出噪声带）：不说「已改善」，不默认采用
UNCONFIRMED_ZH = "数据噪声大，无法确认比初值好，建议保留初值或加长采样后重测"
KEPT_INITIAL_CAUSES_ZH = ["调后参数在某个终验窗口实测代价高于初值"]
UNCONFIRMED_CAUSES_ZH = ["测量噪声大", "采样窗口偏短", "改善幅度小于重复测量的波动"]
NOISE_BAND_K = 2.0
POLISH_SWEEPS = 6            # 达标后继续按代价打磨的圈数（达标不等于接近最优）
GAIN_REL_MIN = 0.02          # 每个终验窗口都要比初值好至少 2%，否则算「无法分辨」
SS_NOISE_K = 2.0
FINAL_WIN_K = (0.5, 0.625, 0.75, 0.875, 1, 1.125, 1.25, 1.375, 1.5, 1.75, 2, 2.5, 3, 4)          # 改善要大于 K × 噪声带（同参数重复测两次代价之差，最好参数与初值各一对）
FLOOR_FRAC = 0.02                                               # 增益下限 = 候选里最大值的 2%、初值的 2% 取大（且不低于声明 min）
FLOOR_INIT = 0.02
STOP_ZH = {"converged": "已满足题面，停止搜索", "budget_exhausted": "试参次数用完仍未满足题面",
           "at_limit": "参数都已顶到声明范围边界，挪不动了"}
# #159 噪声被微分放大顶限幅（只看可观测遥测：执行器输出、传感器读数；门限可在 link 里声明，没写用这里的默认）
NOISE_SAT_FRAC_MIN = 0.3      # link.noise_sat_frac_min：初值执行器饱和时间占比下限
NOISE_U_FRAC_MIN = 0.25       # link.noise_u_frac_min：kd × 噪声斜率 占输出限幅的比例下限
NOISE_SAT_DROP = 0.5          # 调后饱和占比 ≤ 初值 × 这个比例才算“减小微分后好了”


def sat_frac(u, lim: float) -> float:
    u = np.nan_to_num(np.asarray(u, float))
    return float(np.mean(np.abs(u) >= 0.98 * lim)) if math.isfinite(lim) and len(u) else 0.0


def noise_sigma(y) -> float:
    """传感器噪声标准差估计：后半段二阶差分的中位绝对偏差（白噪声二阶差分方差 = 6σ²；平滑响应 / 慢振荡在二阶差分里几乎为 0）。"""
    y = np.nan_to_num(np.asarray(y, float))
    t = y[len(y) // 2:]
    if len(t) < 5:
        return 0.0
    d2 = np.diff(t, 2)
    return float(np.median(np.abs(d2 - np.median(d2))) / 0.6745 / math.sqrt(6))


def noise_amplified_saturation(p0: dict, u0, y0, pb: dict, ub, lim: float, dt: float, link: dict) -> dict | None:
    kd0, kdb = float(p0.get("kd") or 0.0), float(pb.get("kd") or 0.0)
    if not (math.isfinite(lim) and lim > 0 and kd0 > 0 and kdb < kd0):
        return None
    f0, fb = sat_frac(u0, lim), sat_frac(ub, lim)
    sig = noise_sigma(y0)
    du = kd0 * sig * math.sqrt(2) / dt                          # 微分项把噪声放大成的输出跳动
    if f0 >= float(link.get("noise_sat_frac_min") or NOISE_SAT_FRAC_MIN) and du >= float(link.get("noise_u_frac_min") or NOISE_U_FRAC_MIN) * lim \
            and fb <= f0 * NOISE_SAT_DROP:
        return {"code": "noise_amplified_saturation", "sat_frac_initial": f0, "sat_frac_best": fb, "noise_sigma": sig,
                "kd_initial": kd0, "kd_best": kdb, "kd_noise_u": du,
                "message_zh": f"初值微分过大，噪声被放大，执行器约 {f0 * 100:.0f}% 时间饱和；已减小微分（调后约 {fb * 100:.0f}%）"}
    return None


CAUSE_ZH = {"saturation": "执行器饱和", "delay": "纯滞后过大", "nonminimum_phase": "非最小相位（起步反向）"}
LEVEL = {"strong": 3, "medium": 2, "weak": 1}
UNCHANGED_ZH = "初值已满足题面，本次没有改动参数"


def spec_cost(m: dict, sp: dict) -> float:
    """板上代价 = 题面指标超标量（相对题面值，加权大）+ 原 IAE 代价（细分）；题面没写指标 → 退回原代价。"""
    base = cost(m)
    if base >= 1e9:
        return base
    v = 0.0
    for k in ("ss_err_pct", "overshoot_pct", "settle_s"):
        lim = sp.get(k)
        if lim is None:
            continue
        x = m.get(k)
        if x is None or not math.isfinite(x):
            v += 10.0
        else:
            v += max(0.0, x - lim) / (abs(lim) if lim else 1.0)
    return 10.0 * v + base


def ss_noise_floor(m: dict, sp: dict, y, amp: float, n: int) -> list[str]:
    """噪声感知的稳态判定：尾段均值本身有 σ/√N 的不确定度（闭环跟着噪声走，真输出偏差至少这么大）；
    实测稳态误差 + SS_NOISE_K×该不确定度 仍不超限才算达标，否则这一项「测不准」按未达标处理。"""
    lim = sp.get("ss_err_pct")
    if lim is None or m.get("ss_err_pct") is None or not math.isfinite(m["ss_err_pct"]):
        return []
    y = np.asarray(y, float)
    tail = len(y) - int(len(y) * 0.85)
    unc = SS_NOISE_K * noise_sigma(y) / math.sqrt(max(tail, 1)) / (abs(amp) or 1.0) * 100
    return ["ss_err_pct(噪声)"] if m["ss_err_pct"] <= lim < m["ss_err_pct"] + unc else []


def _reproduces(rerun, sp: dict, times: int = 2) -> bool:
    """达标要复现：同参数再跑 times 次（带噪声），每次都满足才算。"""
    return all(not meets(rerun(), sp) for _ in range(times))


def gain_floor(decl: list[dict], cands: list[dict]) -> dict:
    out = {}
    for d in decl:
        if d["role"] in ("kp", "ki") and d["min"] >= 0:
            top = max((abs(float(c.get(d["role"], 0.0))) for c in cands if c), default=0.0)
            out[d["role"]] = max(float(d["min"]), FLOOR_FRAC * top, FLOOR_INIT * abs(float(cands[0].get(d["role"], 0.0))))
    return out


def _clip_floor(p: dict, decl: list[dict], floor: dict) -> dict:
    c = _clip(p, decl)
    return _clip({k: max(v, floor.get(k, -math.inf)) for k, v in c.items()}, decl)


def plant_features(model: "LinModel", dt: float) -> dict:
    """开环特征从辨识模型的阶跃响应读（不从闭环数据猜）：稳态增益 K、积分与否、L/T、起步反向幅度。"""
    from ..agent import stepident
    n = 3000
    f = model.stepper()
    y = np.array([f(1.0) for _ in range(n)])
    if not np.all(np.isfinite(y)):
        return {}
    tail = np.diff(y[-50:]) / dt
    integ = abs(float(np.mean(tail))) > 1e-3 * (abs(y[-1]) + 1e-9) / (n * dt) * 10
    fin = float(y[-1])
    if abs(fin) < 1e-12:
        return {}
    s = 1.0 if fin > 0 else -1.0
    rise = np.where(s * y >= 0.1 * abs(fin))[0]
    inv = max(0.0, -float(np.min(s * y[: (int(rise[0]) if len(rise) else n) + 1])) / abs(fin))
    out = {"integrating": bool(integ), "inv": inv, "K": None if integ else fin, "kv": float(np.mean(tail)) if integ else None}
    if not integ:
        idn = stepident.identify([i * dt for i in range(-3, n)], [0.0] * 3 + list(y), 0.0, 1.0)
        if idn and idn.get("ok") and idn.get("T"):
            out["LT"] = float(idn["L"]) / float(idn["T"])
    return out


def _lvl(x: float, strong: float, medium: float, weak: float):
    return "strong" if x >= strong else "medium" if x >= medium else "weak" if x >= weak else None


def diagnose(feat: dict, bu, by, amp: float, lim: float, win_s: float, bm: dict, sp: dict) -> list[dict]:
    """每个候选原因各自按证据打分（strong / medium / weak），按证据强弱排序；不按固定先后。"""
    out = []
    sgn = 1.0 if amp >= 0 else -1.0
    by = np.nan_to_num(np.asarray(by, float))
    rise = np.where(sgn * by >= 0.1 * abs(amp))[0]
    inv_b = max(0.0, -float(np.min(sgn * by[: (int(rise[0]) if len(rise) else len(by)) + 1])) / abs(amp))
    inv_m = float(feat.get("inv") or 0.0)
    lv = "strong" if inv_m >= 0.05 and inv_b >= 0.03 else _lvl(inv_m, 1e9, 0.08, 0.03)
    if lv:
        out.append({"code": "nonminimum_phase", "evidence": lv, "score": inv_m,
                    "basis_zh": f"辨识模型起步先反向 {inv_m * 100:.1f}%（板上 {inv_b * 100:.1f}%）：非最小相位，快了必反冲"})
    bu = np.nan_to_num(np.asarray(bu, float))
    LT_m = float(feat.get("LT") or 0.0)
    LT_b = _board_LT(bu, by, sgn, abs(amp))
    LT = max(LT_m, LT_b)
    lv = _lvl(LT, 1.5, 0.8, 0.5)
    if lv:
        out.append({"code": "delay", "evidence": lv, "score": LT,
                    "basis_zh": f"纯滞后 / 上升时间 ≈ {LT:.2f}（模型 {LT_m:.2f}，板上 {LT_b:.2f}）：时延过大"})
    satf = float(np.mean(np.abs(bu[: max(len(bu) // 2, 1)]) >= 0.98 * lim)) if math.isfinite(lim) else 0.0
    K = feat.get("K")
    reach = abs(K) * lim / abs(amp) if K is not None and math.isfinite(lim) else None
    lv, basis, sc = None, "", 0.0
    if reach is not None and reach < 0.98:
        lv, sc = ("strong" if reach < 0.9 else "medium"), 1 - reach
        basis = f"按辨识增益，满输出稳态只能到目标的 {reach * 100:.0f}%：执行器饱和"
    elif feat.get("integrating") and feat.get("kv") and sp.get("settle_s") and math.isfinite(lim):
        tmin = abs(amp) / (abs(feat["kv"]) * lim)
        if tmin > 0.7 * float(sp["settle_s"]):
            lv, sc = ("strong" if tmin > sp["settle_s"] else "medium"), tmin / float(sp["settle_s"])
            basis = f"满输出走完阶跃至少要 {tmin:.2g} s（题面调节时间 {sp['settle_s']:g} s）：执行器饱和"
    if lv is None:
        osc = (bm.get("overshoot_pct") or 0.0) > 5.0              # 振荡顶限幅不算饱和证据
        lv = None if osc else _lvl(satf, 1e9, 0.5, 0.3)
        sc = satf
        basis = f"执行器 {satf * 100:.0f}% 时间顶在上限：饱和，再加增益也快不了"
    if lv:
        out.append({"code": "saturation", "evidence": lv, "score": sc, "basis_zh": basis})
    out.sort(key=lambda c: (LEVEL[c["evidence"]], c["score"]), reverse=True)
    return out


def _board_LT(bu, by, sgn: float, a: float) -> float:
    """板上实测：控制量开始动 → 输出开始动（>2%）= 纯滞后；输出 2% → 63% = 上升时间。按拍数比，与采样周期无关。"""
    mu = np.where(np.abs(bu) > 1e-6 * (np.max(np.abs(bu)) if len(bu) else 0) + 1e-12)[0]
    if not len(mu):
        return 0.0
    k0 = int(mu[0])
    ky = np.where(sgn * by[k0:] > 0.02 * a)[0]
    k6 = np.where(sgn * by[k0:] > 0.63 * a)[0]
    if not len(ky) or not len(k6) or k6[0] <= ky[0]:
        return 0.0
    return float(ky[0]) / float(k6[0] - ky[0])


def _close(a: dict, b: dict) -> bool:
    return LEVEL[a["evidence"]] == LEVEL[b["evidence"]]


def _unchanged(seed, sp, amp, n, timing, info, name, p0, m0, c0, amp_reduced, amp_spec, max_step, link) -> dict:
    """初值已满足题面：只按题面判、不改参数、不算“整定成功”；逐项给余量。"""
    extra = {}
    verdict, verdict_zh = "pass", "通过（初值已达标，未调参）"
    if amp_reduced:
        extra = {"amp_reduced": True, "amp_spec": amp_spec, "amp_tested": amp, "amp_unit": link.get("unit") or None,
                 "retest_blocked_by": step_block(amp_spec, max_step, int(link.get("ch") or 0), link.get("unit") or None),
                 "warning_zh": AMP_WARN_ZH}
        verdict, verdict_zh = "partial", "未验题面幅度"
    items = [{"key": k, "spec": sp[k], "measured": m0.get(k), "margin": sp[k] - m0.get(k),
              "verdict": "partial" if amp_reduced else "pass", "verdict_zh": "未验题面幅度" if amp_reduced else "达标"} | extra
             for k in ("ss_err_pct", "overshoot_pct", "settle_s") if sp.get(k) is not None]
    pr = {name[k]: v for k, v in p0.items()}
    return {"seed": seed, "verdict": verdict, "verdict_zh": verdict_zh, "category": None, "pass_basis": UNCHANGED_ZH,
            "spec": sp, "amp": amp, "n": n, "items": items, **extra, "causes": [], "unchanged": True, "unchanged_zh": UNCHANGED_ZH,
            "tuned": False, "margins": {it["key"]: it["margin"] for it in items},
            "stop_reason": "converged", "stop_reason_zh": UNCHANGED_ZH, "budget": 0,
            # 没调参：没有可采用的新参数，卡片契约字段照给（improvement = null，不在三态里）
            "improvement": None, "improvement_confirmed": None, "default_action": "keep_initial", "adopt_default": False, "tuning_causes": [],
            "improvement_info": {"improvement": None, "reason": None, "message_zh": UNCHANGED_ZH, "causes": [], "default_action": "keep_initial"},
            "timing": timing, "ident": info, "initial": {"params": pr, "metrics": m0, "cost": c0},
            "best": {"params": pr, "roles": dict(p0), "metrics": m0, "cost": c0}, "rounds": 0}



def autotune(board, app: dict, link: dict, spec_text: str, seed: int, rounds: int | None = None) -> dict:
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
            write_one(board, d["name"], p[d["role"]], d.get("max_delta"))

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
    amp_spec = float(sp["amp"]) if sp.get("amp") else None
    lims = [x for x in (max_step, (0.5 * rng_phys) if rng_phys else None) if x]
    if lims and abs(amp) > min(lims):
        amp = math.copysign(min(lims), amp)
    amp_reduced = amp_spec is not None and abs(amp) < abs(amp_spec) - 1e-12      # #129：题面幅度超 max_step / 量程，降幅测的
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
    # 4) python-control 模型上搜初值 → 上板迭代（代价与题面指标对齐；收敛 / 预算 / 到边界才停）
    J = lambda m: spec_cost(m, sp)                              # noqa: E731
    hist = [(J(m_init), p0, m_init, (t, r, y, u))]
    if not meets(m_init, sp) and _reproduces(lambda: run(p0, amp, n)[4], sp):
        return _unchanged(seed, sp, amp, n, timing, info, name, p0, m_init, J(m_init), amp_reduced, amp_spec, max_step, link)
    cands = [design(model, decl, amp, dt, n, u_max, rng, p0)] if model else []
    simc = simc_pid(model, decl, dt) if model else None
    if simc:
        cands.append(simc)
    floor = gain_floor(decl, [p0] + cands)                      # 增益下限：不让搜索把增益压到 ≈0（“不动”不算整定）
    for c in cands:
        c = _clip_floor(c, decl, floor)
        res = run(c, amp, n)
        hist.append((J(res[4]), c, res[4], res[:4]))
    tun = [d["role"] for d in decl if d["role"] != "ulim"]
    budget = min(BUDGET_MAX, BUDGET_BASE + BUDGET_PER_PARAM * len(tun)) if rounds is None else rounds
    fac, stop_reason, used, stale = FAC0, "budget_exhausted", 0, 0
    polish_left = POLISH_SWEEPS
    while used < budget:
        ok = [h for h in hist if not meets(h[2], sp)]
        best = min(ok or hist, key=lambda h: h[0])
        if ok:
            stop_reason = "converged"                           # 达标后再打磨 POLISH_SWEEPS 圈（只在达标的参数里比代价），再停
            if polish_left <= 0:
                break
            polish_left -= 1
        improved, moved = False, False
        for r_ in tun:
            for f in (fac, 1 / fac):
                if used >= budget:
                    break
                d = next(x for x in decl if x["role"] == r_)
                base = best[1][r_] if abs(best[1][r_]) > 0 else max(floor.get(r_, 0.0), 1e-6 * (d["max"] or 1))
                c = _clip_floor(dict(best[1], **{r_: base * f}), decl, floor)
                if all(abs(c[k] - best[1][k]) <= 1e-12 * max(1.0, abs(best[1][k])) for k in c):
                    continue                                    # 撞边界，挪不动
                moved = True
                res = run(c, amp, n)
                used += 1
                hist.append((J(res[4]), c, res[4], res[:4]))
                if hist[-1][0] < best[0] * (1 - IMPROVE_REL):
                    best, improved = hist[-1], True
        if not moved:
            stop_reason = "at_limit"
            break
        if not improved:
            fac = math.sqrt(fac)                                # 一圈没变好 → 步子缩小继续；不提前宣布收敛
            stale += 1
            if fac < FAC_MIN:
                fac, stale = FAC0, 0                            # 步子太小 → 重新放大跳出（直到预算用完）
    bc, bp, bm, (bt, br, by, bu) = min([h for h in hist if not meets(h[2], sp)] or hist, key=lambda h: h[0])
    # 终验：窗口加倍复测最好参数与初值（搜索窗口按探测估的调节时间取，可能偏短：慢收敛 / 晚到的振荡在短窗里看不见），
    # 判定与“是否比初值好”都按终验结果（本机实测，不读真值）
    # 多窗口：n / 2n / 4n 每个窗口下都不能比初值差（均值型代价随窗口变：短窗看不见持续稳态误差，长窗冲淡瞬态）
    wins = sorted({int(min(k * n, 40000)) for k in FINAL_WIN_K})
    n_fin = int(min(2 * n, 40000))
    fb = run(bp, amp, n_fin)
    final_check = {"n": n_fin, "windows": []}
    kept_initial = False
    f0 = None
    if bp is not p0:
        for w in wins:
            cb_w = cost((fb if w == n_fin else run(bp, amp, w))[4])
            r0 = run(p0, amp, w)
            if w == n_fin:
                f0 = r0
            c0_w = cost(r0[4])
            final_check["windows"].append({"n": w, "best_cost": cb_w, "initial_cost": c0_w})
            if cb_w > c0_w:
                kept_initial = True
        if kept_initial:                                        # 绝不交付比初值差的参数：退回初值并写明
            bp, fb = p0, f0
    improvement_confirmed = None
    if bp is not p0:
        # 噪声带：同一参数在终验窗口各再测一次，两次代价之差就是这次测量的波动；改善不超过 K×波动 → 不确定
        c0a, cba = final_check["windows"][[x["n"] for x in final_check["windows"]].index(n_fin)]["initial_cost"], cost(fb[4])
        c0b, cbb = cost(run(p0, amp, n_fin)[4]), cost(run(bp, amp, n_fin)[4])
        band = abs(c0a - c0b) + abs(cba - cbb)
        gain = min(c0a, c0b) - max(cba, cbb)
        final_check["noise_band"], final_check["gain"] = band, gain
        improvement_confirmed = bool(gain > NOISE_BAND_K * band and gain > GAIN_REL_MIN * min(c0a, c0b)
                                     and all(x["best_cost"] < (1 - GAIN_REL_MIN) * x["initial_cost"] for x in final_check["windows"]))
    tcause = None
    if bp is not p0 and f0 is not None:
        lim0 = min(u_max, p0.get("ulim", math.inf))
        tcause = noise_amplified_saturation(p0, f0[3], f0[2], bp, fb[3], min(lim0, min(u_max, bp.get("ulim", math.inf))), dt, link)
    reverted_unconfirmed = improvement_confirmed is False
    if reverted_unconfirmed:                                    # 改善不显著（落在噪声带内）→ 同样退回初值，不交付调后参数
        bp, fb = p0, f0
    fw = [x for x in final_check["windows"] if x["n"] == n_fin]
    final_check["best_cost"] = fw[0]["best_cost"] if fw else cost(fb[4])
    final_check["initial_cost"] = fw[0]["initial_cost"] if fw else cost(fb[4])
    bc, bm, (bt, br, by, bu) = J(fb[4]), fb[4], fb[:4]
    n = n_fin
    bad = meets(bm, sp) + ss_noise_floor(bm, sp, by, amp, n)
    if not bad and not _reproduces(lambda: run(bp, amp, n)[4], sp):
        bad = meets(run(bp, amp, n)[4], sp) or ["reproduce"]
    if bad and stop_reason == "converged":
        stop_reason = "budget_exhausted"
    # 5) 诚实判定：按证据给原因（不按固定顺序）
    lim = min(u_max, bp.get("ulim", math.inf))
    feat = plant_features(model, dt) if model else {}
    if not bad:
        verdict, why, cat, causes = "pass", "各项指标实测满足题面", None, []
        verdict_zh = "达标"
    else:
        verdict = "fail"
        causes = diagnose(feat, bu, by, amp, lim, n * dt, bm, sp)
        cat = causes[0]["code"] if causes else "unconfirmed"
        if len(causes) >= 2 and _close(causes[0], causes[1]):
            verdict_zh = f"未达标：可能是{CAUSE_ZH[causes[0]['code']]}或{CAUSE_ZH[causes[1]['code']]}"
        else:
            verdict_zh = "未达标" + (f"：{CAUSE_ZH[cat]}" if cat in CAUSE_ZH else "")
        why = (causes[0]["basis_zh"] if causes else "原因待确认：特征不足以归类") + "；未达标：" + "、".join(bad)
    if kept_initial:
        verdict_zh = KEPT_INITIAL_ZH + "；" + verdict_zh
        why = KEPT_INITIAL_ZH + "（调后实测代价高于初值）；" + why
    extra = {}
    unconf = improvement_confirmed is False
    if unconf:
        why = UNCONFIRMED_ZH + "；" + why
        verdict_zh = UNCONFIRMED_ZH + "；" + verdict_zh
    if tcause and not kept_initial:
        why = tcause["message_zh"] + "；" + why
    imp = "worse" if kept_initial else ("inconclusive" if unconf else "confirmed")
    if imp == "worse":
        info = {"reason": "kept_initial", "message_zh": KEPT_INITIAL_ZH, "causes": KEPT_INITIAL_CAUSES_ZH}
    elif imp == "inconclusive":
        info = {"reason": "improvement_unconfirmed", "message_zh": UNCONFIRMED_ZH, "causes": UNCONFIRMED_CAUSES_ZH}
    else:
        info = {"reason": None, "message_zh": None, "causes": []}
    dflt = "adopt" if imp == "confirmed" else "keep_initial"
    # 卡片契约：improvement ∈ confirmed|inconclusive|worse；顶层 reason / message_zh；整定原因码的 causes 放 improvement_info（顶层 causes 是未达标诊断）
    extra_u = {"tuning_causes": [tcause] if tcause else [], "improvement": imp, "improvement_confirmed": improvement_confirmed, "default_action": dflt, "adopt_default": dflt == "adopt",
               "improvement_info": {"improvement": imp, **info, "default_action": dflt},
               **({"reason": info["reason"], "message_zh": info["message_zh"], "unconfirmed_causes": info["causes"]} if info["reason"] else {})}
    if amp_reduced:                                             # #129：降幅测的 pass 不是题面的 pass
        extra = {"amp_reduced": True, "amp_spec": amp_spec, "amp_tested": amp, "amp_unit": link.get("unit") or None, "amp_unit_decl": link.get("unit_decl") or None,
                 "retest_blocked_by": step_block(amp_spec, max_step, int(link.get("ch") or 0), link.get("unit") or None),
                 "warning_zh": AMP_WARN_ZH}
        if verdict == "pass":
            verdict, verdict_zh, why = "partial", "未验题面幅度", why + f"（按降幅 {amp:g} 测，题面 {amp_spec:g} 超 max_step / 量程）"
    items = []
    for k in ("ss_err_pct", "overshoot_pct", "settle_s"):        # metrics_card items[]
        if sp.get(k) is None:
            continue
        v = "fail" if k in bad else ("partial" if amp_reduced else "pass")
        mv = bm.get(k)
        items.append({"key": k, "spec": sp[k], "measured": mv, "margin": (sp[k] - mv) if mv is not None and math.isfinite(mv) else None,
                      "verdict": v} | extra)
    for it in items:
        it["verdict_zh"] = {"pass": "达标", "fail": "未达标", "partial": "未验题面幅度"}[it["verdict"]]
    return {"seed": seed, "verdict": verdict, "verdict_zh": verdict_zh, "category": cat, "pass_basis": why, "spec": sp, "amp": amp, "n": n,
            "items": items, **extra, "causes": causes, "stop_reason": stop_reason, "stop_reason_zh": STOP_ZH[stop_reason],
            "unchanged": kept_initial or reverted_unconfirmed, "tuned": not (kept_initial or reverted_unconfirmed), "kept_initial": kept_initial, "final_check": final_check, "cost_initial": final_check["initial_cost"], "cost_best": final_check["best_cost"],
            **({"reason_zh": KEPT_INITIAL_ZH} if kept_initial else {}), "budget": budget, **extra_u,
            "timing": timing, "ident": info, "initial": {"params": {name[k]: v for k, v in p0.items()}, "metrics": m_init, "cost": cost(m_init)},
            "best": {"params": {name[k]: v for k, v in bp.items()}, "roles": bp, "metrics": bm, "cost": bc},
            "rounds": len(hist) - 1}
