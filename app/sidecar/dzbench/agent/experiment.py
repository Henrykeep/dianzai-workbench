"""调参实验与打分：相对基线归一化打分 + 权重模板、四段正负阶跃、带原因码的稳态判定、分阶段 P→I→D 搜索、开环/群体搜索门禁。

思路来源：PID_Helper（gitee.com/qianmonai，GPL-3.0）——**只借鉴思路，本文件代码全部自写**，未拷贝其任何源码。
见 docs/参考来源.md、docs/QUESTIONS.md 第 23 条。全部只在仿真/基准上验证过，未上实机。
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from .guard import GuardError, TuneGuard, stable
from .tuning import StepMetrics, step_metrics

# ---------------------------------------------------------------- 1. 相对基线打分
# 指标：iae（÷幅度）、overshoot、|sse|、settling、osc。每项 (x+floor)/(基线+floor)，再按权重平均：
# 1.0 = 和第一轮一样，<1 更好。量纲/单位无关，sp=0 也成立。floor 防止基线指标≈0 时比值爆炸。
FLOORS = {"iae": 0.02, "overshoot": 2.0, "sse": 0.5, "settling": 0.05, "osc": 1.0}
WEIGHTS = {
    "balanced":     {"iae": 1.0, "overshoot": 1.0, "sse": 1.0, "settling": 0.5, "osc": 0.5},
    "conservative": {"iae": 0.5, "overshoot": 2.0, "sse": 1.0, "settling": 0.3, "osc": 1.5},   # 怕超调/振荡（钢珠、平衡）
    "actuator":     {"iae": 0.5, "overshoot": 1.0, "sse": 0.5, "settling": 0.3, "osc": 2.5},   # 护执行器：振荡=电机来回换向
}


def features(m: StepMetrics, t_end: float | None = None) -> dict:
    amp = abs(m.target - m.y0) or 1.0
    return {"iae": m.iae / amp, "overshoot": m.overshoot_pct, "sse": abs(m.sse_pct),
            "settling": m.settling_s if m.settling_s is not None else (t_end or 2.0), "osc": float(m.oscillations)}


def rel_score(m: StepMetrics, base: StepMetrics, weights: str | dict = "balanced", floors: dict | None = None) -> float:
    if not m.ok:
        return math.inf
    w = WEIGHTS[weights] if isinstance(weights, str) else weights
    fl = {**FLOORS, **(floors or {})}
    a, b = features(m), features(base)
    s = sum(w[k] * (a[k] + fl[k]) / (b[k] + fl[k]) for k in w) / sum(w.values())
    return s + (0.0 if stable(m) else 1.0)


# ---------------------------------------------------------------- 2. 稳态判定（带原因码）
REASONS = {"steady": "已稳态", "too_few_samples": "样本太少", "warming_up": "刚开始/刚阶跃，还在暖机",
           "still_drifting": "还在漂移（窗口首尾差超过噪声）", "too_little_motion": "几乎没动：激励太小或执行器没响应",
           "oscillating": "在稳态附近持续振荡"}


def _median3(y):
    return [statistics.median(y[max(0, i - 1):i + 2]) for i in range(len(y))]


def steady_state(t: list[float], y: list[float], window_s: float = 0.3, warmup_s: float = 0.2,
                 span_ref: float | None = None) -> dict:
    """返回 {steady, reason, text, noise, drift}。先 3 点中值滤波再 EMA；阈值 = max(3×噪声, 1% 参考幅度)，随噪声自适应。
    reason 给 Agent/人看：warming_up / still_drifting → 应 OBSERVE（多等一会儿）而不是改参数。"""
    if len(t) < 10 or t[-1] - t[0] < window_s:
        return _ss(False, "too_few_samples")
    if t[-1] - t[0] < warmup_s + window_s:
        return _ss(False, "warming_up")
    i0 = next(i for i, v in enumerate(t) if v >= t[-1] - window_s)
    raw = y[i0:]
    f = _median3(raw)
    # 噪声 = 原始值相对 3 点中值的残差（MAD×1.4826）：只含高频抖动，不会被慢振荡/漂移撑大
    res = sorted(abs(r - q) for r, q in zip(raw, f))
    noise = 1.4826 * res[len(res) // 2]
    ema = [f[0]]
    for v in f[1:]:
        ema.append(ema[-1] + 0.3 * (v - ema[-1]))
    ref = span_ref if span_ref is not None else (max(y) - min(y))
    if span_ref is not None and abs(span_ref) < 1e-6:
        return _ss(False, "too_little_motion", noise)
    thr = max(3 * noise, 0.01 * abs(ref), 1e-9)
    mean = sum(ema) / len(ema)
    cross, side = 0, 0
    for v in ema:                                    # 带滞回的均值穿越
        sd = 1 if v > mean + thr else -1 if v < mean - thr else 0
        if sd and side and sd != side:
            cross += 1
        if sd:
            side = sd
    n3 = max(1, len(ema) // 3)
    drift = abs(sum(ema[-n3:]) / n3 - sum(ema[:n3]) / n3)
    if cross >= 3:
        return _ss(False, "oscillating", noise, drift)
    if drift > thr:
        return _ss(False, "still_drifting", noise, drift)
    return _ss(True, "steady", noise, drift)


def _ss(ok, reason, noise=0.0, drift=0.0):
    return {"steady": ok, "reason": reason, "text": REASONS[reason], "noise": round(noise, 6), "drift": round(drift, 6)}


# ---------------------------------------------------------------- 3. 四段正负阶跃
def four_segment_plan(sp: float, delta: float, hold_s: float) -> list[tuple[float, float]]:
    """SP → SP−Δ → SP → SP+Δ → SP：返回 [(开始时刻, 设定值)]。同时看两个方向（摩擦/重力不对称）。"""
    if delta <= 0 or hold_s <= 0:
        raise GuardError("bad_plan", "delta 与 hold_s 必须 > 0")
    vals = [sp, sp - delta, sp, sp + delta, sp]
    return [(k * hold_s, v) for k, v in enumerate(vals)]


def four_segment_metrics(t: list[float], y: list[float], sp: list[float], plan: list[tuple[float, float]]) -> list[dict]:
    """把一次四段实验切成 4 个阶跃分别出指标（第 0 段只做预热）。每段：方向、超调、调节、稳态误差、振荡。"""
    out = []
    for k in range(1, len(plan)):
        a = plan[k - 1][0] + 0.5 * (plan[k][0] - plan[k - 1][0])          # 取上一段后半作阶跃前基线
        b = plan[k + 1][0] if k + 1 < len(plan) else t[-1] + 1e-9
        idx = [i for i, v in enumerate(t) if a <= v < b]
        if len(idx) < 10:
            out.append({"seg": k, "ok": False, "reason": "该段数据太少"}); continue
        m = step_metrics([t[i] for i in idx], [y[i] for i in idx], [sp[i] for i in idx])
        d = m.as_dict()
        d.update(seg=k, dir="down" if plan[k][1] < plan[k - 1][1] else "up")
        out.append(d)
    return out


def asymmetry(segs: list[dict]) -> dict | None:
    """上/下方向对比：差别大 → 摩擦/重力不对称，提示加前馈或静摩擦补偿，而不是硬拧 PID。"""
    up = [s for s in segs if s.get("ok") and s["dir"] == "up"]
    dn = [s for s in segs if s.get("ok") and s["dir"] == "down"]
    if not up or not dn:
        return None
    f = lambda L, k: sum(abs(s[k]) for s in L) / len(L)  # noqa: E731
    r = {k: (round(f(up, k), 3), round(f(dn, k), 3)) for k in ("overshoot_pct", "sse_pct")}
    r["asymmetric"] = any(abs(u - d) > max(3.0, 0.5 * max(u, d)) for u, d in r.values())
    return r


# ---------------------------------------------------------------- 4. 分阶段 P→I→D 搜索（无 LLM 默认）
@dataclass
class StagedSearch:
    """每轮只动一个增益，阶段 P → I → D：本阶段持续往一个方向乘 factor，
    指标变好就继续，变差（护栏标 last_rejected）或越过"够用"线就进入下一阶段。所有提议都要过 TuneGuard.check。
    与 PID_Helper 的"纯 P 静差 15–20% 目标"不同：我们不把 I 清零（实机上 I 不能一步降到 0），而是从当前值出发。"""
    order: tuple = ("kp", "ki", "kd")
    factor: float = 1.3
    stage: int = 0
    direction: int = 0
    log: list = field(default_factory=list)

    def _dir_for(self, p: str, m: StepMetrics) -> int:
        if m.oscillations >= 3 or m.overshoot_pct > 25:
            return -1 if p != "kd" else +1
        if p == "kp":
            return +1 if m.overshoot_pct < 5 else -1
        if p == "ki":
            return +1 if abs(m.sse_pct) > 1.0 else (-1 if m.overshoot_pct > 10 else 0)
        return +1 if m.overshoot_pct > 10 else 0

    def propose(self, m: StepMetrics, gains: dict, g: TuneGuard) -> tuple[str, float] | None:
        order = [p for p in self.order if p in gains]
        last = g.rounds[-1] if g.rounds else None
        if last and last.label == "last_rejected" and last.changed and self.stage < len(order) and last.changed[0] == order[self.stage]:
            self.stage, self.direction = self.stage + 1, 0          # 本阶段方向已证明变差：下一阶段
        while self.stage < len(order):
            p = order[self.stage]
            d = self.direction or self._dir_for(p, m)
            if d and (p, d) not in g.blocked:
                self.direction = d
                cur = gains[p]
                lo, hi = g.bounds.get(p, (0.0, None))
                want = cur * (self.factor if d > 0 else 1 / self.factor) if cur else (hi or 1.0) * 0.02
                try:
                    v, _ = g.check(p, cur, want)
                except GuardError:
                    v = None
                if v is not None and v != cur:
                    self.log.append((self.stage, p, d))
                    return p, v
            self.stage, self.direction = self.stage + 1, 0
        return None


# ---------------------------------------------------------------- 5. 门禁
def require_open_loop(cfg_step: dict, sim: bool) -> None:
    """开环阶跃/FOPDT 辨识只对稳定对象（电机速度环）开放；钢珠、平衡等不稳定/积分对象开环会跑飞。"""
    if not cfg_step.get("plant_stable", False):
        raise GuardError("plant_unstable", "开环实验需要在 dzbench.json step_test.plant_stable=true（只对稳定对象，如电机速度环）；"
                         "钢珠/平衡车请用闭环小幅阶跃")
    if not sim and not cfg_step.get("open_loop_max"):
        raise GuardError("no_limit", "实机开环必须配置 step_test.open_loop_max（输出幅度上限，建议 0.1–0.4）")


def require_swarm(sim: bool) -> None:
    """群体/随机搜索（PSO 等）轮次多、有随机性、可能跳到边界：只许在仿真里跑，实机只验证它给出的 top-k 候选。"""
    if not sim:
        raise GuardError("swarm_hw", "群体搜索只能在仿真里跑；实机请逐个验证仿真给出的候选（每个都过护栏）")
