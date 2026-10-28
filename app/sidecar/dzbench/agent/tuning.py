"""阶跃响应指标与规则调参建议（离线，不需要 LLM）。

指标定义按经典控制教材（Ogata《现代控制工程》§5-3；MATLAB stepinfo 同口径）：
  上升时间 10%→90%、超调 %、调节时间（进入并保持在 ±band 内）、稳态误差、振荡次数（误差过零次数）、IAE。
规则参考 Ziegler–Nichols 之后的经验整定口诀（Åström & Hägglund《PID Controllers》第 4 章）：
  超调大 → 减 Kp / 加 Kd；振荡持续 → 减 Kp、减 Ki；上升慢 → 加 Kp；稳态误差 → 加 Ki；输出饱和 → 先别加增益。
每条建议都给出“为什么”和保守步长（默认 15%），最终仍由人确认、由网关限幅。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class StepMetrics:
    ok: bool
    reason: str = ""
    t0: float = 0.0
    y0: float = 0.0
    target: float = 0.0
    rise_s: float | None = None
    overshoot_pct: float = 0.0
    settling_s: float | None = None
    sse: float = 0.0
    sse_pct: float = 0.0
    oscillations: int = 0
    iae: float = 0.0
    saturated: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def find_step(t: list[float], sp: list[float], tol: float = 0.01) -> int | None:
    """最后一次设定值变化（阶跃或斜坡）的起点。设定值经过加速度限幅时是斜坡，起点取斜坡开始处。"""
    final = sp[-1]
    span = max(sp) - min(sp)
    if span <= 1e-9:
        return None
    far = [i for i, v in enumerate(sp) if abs(v - final) > tol * span]
    if not far:
        return None
    i = far[-1]
    while i > 0 and abs(sp[i] - sp[i - 1]) > 1e-9:
        i -= 1
    return max(i, 1) if i + 1 < len(sp) else None


def step_metrics(t: list[float], y: list[float], sp: list[float], band: float = 0.05,
                 u: list[float] | None = None, u_limit: float | None = None) -> StepMetrics:
    if len(t) < 10 or len(t) != len(y) or len(y) != len(sp):
        return StepMetrics(False, "数据太少（至少 10 点，且 t/y/sp 等长）")
    i0 = find_step(t, sp)
    if i0 is None:
        return StepMetrics(False, "没找到设定值阶跃：先给一个阶跃（例如从 0 跳到目标值）再分析")
    seg = range(i0, len(t))
    t0, y0, r = t[i0], y[i0 - 1], sp[-1]
    amp = r - y0
    if abs(amp) < 1e-9:
        return StepMetrics(False, "阶跃幅度为 0")
    if t[-1] - t0 < 0.2:
        return StepMetrics(False, "阶跃后数据不足 0.2 s，多录一会儿")
    n = lambda v: (v - y0) / amp                     # 归一化：0 起点，1 目标
    ys = [n(y[i]) for i in seg]
    ts = [t[i] - t0 for i in seg]
    m = StepMetrics(True, t0=t0, y0=y0, target=r)
    t10 = next((ts[k] for k, v in enumerate(ys) if v >= 0.1), None)
    t90 = next((ts[k] for k, v in enumerate(ys) if v >= 0.9), None)
    m.rise_s = (t90 - t10) if t10 is not None and t90 is not None else None
    m.overshoot_pct = max(0.0, (max(ys) - 1.0) * 100.0)
    out = [k for k, v in enumerate(ys) if abs(v - 1.0) > band]
    if not out:
        m.settling_s = 0.0
    elif out[-1] < len(ys) - 1:
        m.settling_s = ts[out[-1] + 1]
    tail = ys[int(len(ys) * 0.8):]
    final = sum(tail) / len(tail)
    m.sse_pct = (1.0 - final) * 100.0
    m.sse = (1.0 - final) * amp
    e = [1.0 - v for v in ys]
    m.oscillations = _crossings(e, band / 2)
    m.iae = sum(abs(e[k]) * (ts[k + 1] - ts[k]) for k in range(len(ts) - 1)) * abs(amp)
    if u is not None and u_limit:
        us = [abs(u[i]) for i in seg]
        m.saturated = sum(1 for v in us if v >= 0.98 * u_limit) > 0.2 * len(us)
    return m


def _crossings(e: list[float], hyst: float) -> int:
    """误差带滞回的过零次数：噪声在 ±hyst 内抖不算。"""
    n, sign = 0, 0
    for v in e:
        s = 1 if v > hyst else -1 if v < -hyst else 0
        if s and sign and s != sign:
            n += 1
        if s:
            sign = s
    return n


@dataclass
class Hint:
    level: str            # info / warn
    text: str
    changes: dict = field(default_factory=dict)   # 参数名 → 建议值（未限幅，网关会限幅）

    def as_dict(self) -> dict:
        return asdict(self)


def tuning_hints(m: StepMetrics, gains: dict[str, float], kp: str = "kp", ki: str = "ki", kd: str | None = "kd",
                 step: float = 0.15, os_max: float = 10.0, sse_max: float = 2.0) -> list[Hint]:
    """规则建议。gains 是当前参数值；kp/ki/kd 给出参数名（没有 Kd 的环传 None）。"""
    if not m.ok:
        return [Hint("info", m.reason)]
    h: list[Hint] = []
    g = lambda k: gains.get(k) if k else None
    rnd = lambda v: float(f"{v:.4g}")
    if m.saturated:
        h.append(Hint("warn", "输出长时间顶到限幅：此时加增益没用，响应快慢由执行器能力决定。先确认限幅/供电，或减小阶跃幅度再整定。"))
        return h
    if m.oscillations >= 3 or (m.settling_s is None and m.overshoot_pct > os_max):
        c = {}
        if g(kp) is not None:
            c[kp] = rnd(g(kp) * (1 - 2 * step))
        if g(ki):
            c[ki] = rnd(g(ki) * (1 - step))
        h.append(Hint("warn", f"持续振荡（过零 {m.oscillations} 次{'，未进入稳定带' if m.settling_s is None else ''}）：先降 Kp 约 {int(2*step*100)}%、Ki 约 {int(step*100)}%。", c))
        return h
    if m.overshoot_pct > os_max:
        c = {}
        if kd and g(kd) is not None:
            c[kd] = rnd((g(kd) or 0) * (1 + 2 * step) if g(kd) else max(g(kp) or 0, 1e-3) * 0.05)
            why = "加阻尼（Kd）"
        elif g(kp) is not None:
            c[kp] = rnd(g(kp) * (1 - step))
            why = "降 Kp（这个环没有 Kd）"
        else:
            why = "降增益"
        h.append(Hint("warn", f"超调 {m.overshoot_pct:.1f}%（目标 ≤{os_max:.0f}%）：{why}。", c))
    elif m.rise_s is not None and m.overshoot_pct < 1.0 and m.sse_pct < sse_max and g(kp) is not None:
        h.append(Hint("info", f"几乎无超调（{m.overshoot_pct:.1f}%），上升 {m.rise_s:.3f} s：还有余量，可试加 Kp {int(step*100)}% 提速。",
                      {kp: rnd(g(kp) * (1 + step))}))
    if m.rise_s is None:
        h.append(Hint("warn", "没到 90% 目标：增益太小或负载太大。检查方向/接线后加 Kp。",
                      {kp: rnd(g(kp) * (1 + 2 * step))} if g(kp) is not None else {}))
    if abs(m.sse_pct) > sse_max:
        c = {ki: rnd((g(ki) or 0) * (1 + 2 * step) if g(ki) else max(g(kp) or 0, 1e-3) * 0.1)} if ki and ki in gains else {}
        h.append(Hint("warn", f"稳态误差 {m.sse_pct:.1f}%：{'加 Ki' if c else '这个环没有积分项，考虑加 Ki 或前馈'}。", c))
    if not h:
        h.append(Hint("info", f"响应良好：超调 {m.overshoot_pct:.1f}%，调节 {m.settling_s:.3f} s，稳态误差 {m.sse_pct:.1f}%。建议存快照。"))
    return h
