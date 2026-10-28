"""AI 调参护栏：LLM（或规则）只提议，收敛/回滚/停止由这里按实测指标判定。

思路来源：llm-pid-tuner（KINGSTON-115，MIT，Copyright 2026 Charles Liang）的 pid_safety / 历史表 / OBSERVE。
本文件为自写实现，并修正了审阅中指出的问题（docs/QUESTIONS.md 第 16~19 条）：
- 指标来自真实阶跃实验，超调/稳态误差按阶跃幅度归一化（sp=0 也成立），阈值全是相对量；过零检测带滞回（tuning.py）。
- 双向比例限幅 + 绝对单步上限 + 0 起步小值；实机档比仿真档更保守。
- 每轮只改一个增益；已证明变差的方向下一轮禁止；实机最多 8 轮，电量/温度越限即停。
- 实机回滚到最好参数要人点（仿真可自动）。
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

from .tuning import StepMetrics


@dataclass
class Profile:
    ratio_up: float          # 新值 ≤ 当前 × (1+ratio_up)
    ratio_down: float        # 新值 ≥ 当前 × (1−ratio_down)
    max_step_frac: float     # 单步绝对变化 ≤ 量程 × frac
    zero_start_frac: float   # 当前为 0 时，第一步 ≤ 量程 × frac
    max_rounds: int
    auto_rollback: bool


HW = Profile(0.5, 0.3, 0.10, 0.02, 8, False)
SIM = Profile(2.0, 0.6, 0.25, 0.05, 20, True)

# good-enough（全是相对量）：超调 ≤ 10%，|稳态误差| ≤ 2% 阶跃幅度，已进入 2% 带，振荡 ≤ 1 次；连续 2 轮
GOOD = {"overshoot_pct": 10.0, "sse_pct": 2.0, "osc": 1, "consecutive": 2}
LIMITS = {"vbat_min": None, "temp_max": None}     # 由分层配置覆盖（config.py: tune.vbat_min / tune.temp_max）
VBAT_FIELDS, TEMP_FIELDS = ("vbat", "batt_v", "vbat_v", "bat_v"), ("temp", "temp_c", "mos_temp", "motor_temp")


class GuardError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def stable(m: StepMetrics) -> bool:
    return m.ok and m.settling_s is not None and m.oscillations <= 2 and m.overshoot_pct <= 40


def good_enough(m: StepMetrics, good=GOOD) -> bool:
    return (m.ok and m.settling_s is not None and m.overshoot_pct <= good["overshoot_pct"]
            and abs(m.sse_pct) <= good["sse_pct"] and m.oscillations <= good["osc"])


def score(m: StepMetrics) -> float:
    """越小越好。全部无量纲：归一化 IAE（÷|阶跃幅度|）+ 超调/稳态误差比例 + 振荡次数；不稳定加罚。"""
    if not m.ok:
        return math.inf
    amp = abs(m.target - m.y0) or 1.0
    s = m.iae / amp + m.overshoot_pct / 100 + abs(m.sse_pct) / 100 + 0.1 * m.oscillations
    return s + (0 if stable(m) else 1.0)


@dataclass
class Round:
    n: int
    gains: dict
    metrics: dict
    score: float
    label: str = "recent"            # best / last_rejected / recent
    changed: tuple | None = None     # (参数, +1/-1)


@dataclass
class TuneGuard:
    bounds: dict                      # name → (min, max)，来自板上 schema（dzctl 还会再限幅一次）
    sim: bool = True
    good: dict = field(default_factory=lambda: dict(GOOD))
    limits: dict = field(default_factory=lambda: dict(LIMITS))
    rounds: list = field(default_factory=list)
    blocked: set = field(default_factory=set)       # 已证明变差的 (参数, 方向)
    proposed_this_round: str | None = None
    stopped: str = ""
    max_rounds: int | None = None     # 覆盖档位默认；实机上限 10（service 里 min(配置, 10)）

    @property
    def profile(self) -> Profile:
        p = SIM if self.sim else HW
        return p if self.max_rounds is None else Profile(**{**p.__dict__, "max_rounds": self.max_rounds})

    def best(self) -> Round | None:
        st = [r for r in self.rounds if r.label != "unstable"]
        return min(st, key=lambda r: r.score) if st else None

    # ---------------------------------------------------------------- 每轮实测后
    def record(self, m: StepMetrics, gains: dict, sample: dict | None = None) -> dict:
        """记录一轮实测，返回程序判定：continue / done / rollback / stop。"""
        prev = self.rounds[-1] if self.rounds else None
        r = Round(len(self.rounds) + 1, dict(gains), m.as_dict(), score(m))
        if prev:
            diff = [(k, 1 if gains[k] > prev.gains.get(k, 0) else -1) for k in gains if gains[k] != prev.gains.get(k)]
            r.changed = diff[0] if len(diff) == 1 else None
        if not stable(m):
            r.label = "unstable"
        self.rounds.append(r)
        self.proposed_this_round = None
        best = self.best()
        if prev and r.changed and r.score > prev.score * 1.05:
            r.label = "last_rejected"
            self.blocked.add(r.changed)
        else:
            self.blocked = {b for b in self.blocked if not r.changed or b[0] != r.changed[0]}
        for x in self.rounds:
            if x.label == "best":
                x.label = "recent"
        if best and best.label not in ("unstable", "last_rejected"):
            best.label = "best"
        verdict = {"round": r.n, "score": round(r.score, 4), "stable": stable(m), "good_enough": good_enough(m, self.good)}
        why = self._env_stop(sample or {})
        tail = self.rounds[-self.good["consecutive"]:]
        if why:
            self.stopped = why
            verdict["action"] = "stop"
        elif len(tail) == self.good["consecutive"] and all(good_enough(StepMetrics(**x.metrics), self.good) for x in tail):
            self.stopped = "达标（连续 %d 轮 good-enough）" % self.good["consecutive"]
            verdict["action"] = "done"
        elif len(self.rounds) >= self.profile.max_rounds:
            self.stopped = f"已到 {self.profile.max_rounds} 轮上限"
            verdict["action"] = "stop"
        elif best and best is not r and (not stable(m) or r.score > best.score * 1.3):
            verdict["action"] = "rollback"
            verdict["auto"] = self.profile.auto_rollback
        else:
            verdict["action"] = "continue"
        if best:
            verdict["best"] = {"round": best.n, "gains": best.gains, "score": round(best.score, 4)}
        verdict["reason"] = self.stopped
        return verdict

    def _env_stop(self, sample: dict) -> str:
        vb = next((sample[f] for f in VBAT_FIELDS if f in sample), None)
        tc = next((sample[f] for f in TEMP_FIELDS if f in sample), None)
        if self.limits.get("vbat_min") is not None and vb is not None and vb < self.limits["vbat_min"]:
            return f"电池电压 {vb:.2f} V 低于 {self.limits['vbat_min']} V，停止调参（换电池后各轮不可比）"
        if self.limits.get("temp_max") is not None and tc is not None and tc > self.limits["temp_max"]:
            return f"温度 {tc:.1f} °C 超过 {self.limits['temp_max']} °C，停止调参"
        return ""

    # ---------------------------------------------------------------- 每次提议前
    def check(self, name: str, cur: float | None, value: float) -> tuple[float, list[str]]:
        """返回 (强制后的值, 说明)。违反“每轮一项 / 禁止方向 / 已停止”直接拒绝。"""
        if self.stopped:
            raise GuardError("tune_stopped", f"调参已结束：{self.stopped}。要继续请人工重置护栏")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise GuardError("bad_value", "参数值必须是有限数字")
        if self.proposed_this_round and self.proposed_this_round != name:
            raise GuardError("one_gain", f"本轮已提议改 {self.proposed_this_round}；每轮只改一个参数，先做阶跃实验看结果")
        lo, hi = self.bounds.get(name, (-math.inf, math.inf))
        span = (hi - lo) if math.isfinite(hi - lo) else max(abs(cur or 1.0), 1.0)
        cur = float(cur or 0.0)
        d = 1 if value > cur else -1 if value < cur else 0
        if d and (name, d) in self.blocked:
            raise GuardError("bad_direction", f"上一轮把 {name} 往{'大' if d > 0 else '小'}调已证明变差，不要重复；换一个参数或 OBSERVE")
        p, notes, v = self.profile, [], float(value)
        if cur == 0.0 and d > 0:
            cap = lo + span * p.zero_start_frac if lo > 0 else span * p.zero_start_frac
            if v > cap:
                v, _ = cap, notes.append(f"{name} 从 0 起步，第一步限到 {cap:.4g}")
        else:
            up, dn = abs(cur) * (1 + p.ratio_up), abs(cur) * (1 - p.ratio_down)
            if cur > 0 and v > up:
                v, _ = up, notes.append(f"单步增幅限到 ×{1 + p.ratio_up:g}")
            if cur > 0 and v < dn:
                v, _ = dn, notes.append(f"单步降幅限到 ×{1 - p.ratio_down:g}")
        step = span * p.max_step_frac
        if abs(v - cur) > step:
            v, _ = cur + math.copysign(step, v - cur), notes.append(f"单步绝对变化限到 {step:.4g}")
        if v < lo or v > hi:
            v, _ = min(max(v, lo), hi), notes.append("限到参数范围")
        self.proposed_this_round = name
        return v, notes

    # ---------------------------------------------------------------- 给 LLM 的紧凑上下文
    def prompt_rules(self) -> str:
        p = self.profile
        return (f"调参护栏（运行时强制执行）：每轮只改一个参数；单步增幅 ≤×{1 + p.ratio_up:g}、降幅 ≥×{1 - p.ratio_down:g}、"
                f"绝对变化 ≤ 量程×{p.max_step_frac:g}；参数为 0 时第一步 ≤ 量程×{p.zero_start_frac:g}；"
                f"最多 {p.max_rounds} 轮；证据不足就回复 OBSERVE；已变差的方向不要重复；DONE 只是建议，是否达标由程序按实测判定。")

    def history_table(self, n: int = 5) -> list[dict]:
        keep = {id(r) for r in self.rounds[-n:]} | {id(r) for r in self.rounds if r.label in ("best", "last_rejected")}
        return [{"round": r.n, "label": r.label, "gains": r.gains, "score": round(r.score, 4),
                 **{k: r.metrics.get(k) for k in ("overshoot_pct", "settling_s", "sse_pct", "oscillations")}}
                for r in self.rounds if id(r) in keep]


def key_samples(t: list[float], y: list[float], sp: list[float], n: int = 20) -> list[list[float]]:
    """保留极值和设定值跳变点的样本压缩（不盲目抽稀）。思路参考 llm-pid-tuner（MIT）。"""
    if len(t) <= n:
        return [[round(a, 4), round(b, 5), round(c, 5)] for a, b, c in zip(t, y, sp)]
    must = [0, len(t) - 1, y.index(max(y)), y.index(min(y))] + [i for i in range(1, len(sp)) if sp[i] != sp[i - 1]]
    rest, buckets = [], max(1, n // 2)
    w = len(t) / buckets
    for b in range(buckets):
        seg = range(int(b * w), min(len(t), int((b + 1) * w)))
        if seg:
            rest += [max(seg, key=lambda i: y[i]), min(seg, key=lambda i: y[i])]
    pick: list[int] = []
    for i in must + rest:
        if i not in pick and len(pick) < n:
            pick.append(i)
    pick.sort()
    return [[round(t[i], 4), round(y[i], 5), round(sp[i], 5)] for i in pick]


_JSON_OBJ = re.compile(r"\{")


def parse_reply(text: str) -> dict:
    """严格解析模型回复：只认第一个完整 JSON 对象；action ∈ PROPOSE/OBSERVE/DONE；拒绝 bool/NaN/溢出；不从散文里猜参数。"""
    dec = json.JSONDecoder(parse_constant=lambda c: (_ for _ in ()).throw(GuardError("bad_reply", f"非法数值 {c}")))
    for m in _JSON_OBJ.finditer(text or ""):
        try:
            obj, _ = dec.raw_decode(text, m.start())
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        act = str(obj.get("action", "")).upper()
        if act not in ("PROPOSE", "OBSERVE", "DONE"):
            raise GuardError("bad_reply", "action 必须是 PROPOSE / OBSERVE / DONE")
        out = {"action": act, "reason": str(obj.get("reason", ""))[:500]}
        if act == "PROPOSE":
            name, v = obj.get("param"), obj.get("value")
            if not isinstance(name, str) or isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 1e9:
                raise GuardError("bad_reply", "PROPOSE 需要 param（字符串）和有限数字 value")
            out |= {"param": name, "value": float(v)}
        return out
    raise GuardError("bad_reply", "回复里没有 JSON 对象")
