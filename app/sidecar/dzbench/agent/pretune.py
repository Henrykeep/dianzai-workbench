"""调参前问答（缺口清单第 9 项）：先问对象类型 / 执行器 / 安全限 / 目标，再让 Agent 和护栏按这些出初值、打分。

思路与字段名取自 llm-pid-tuner（MIT，Copyright (c) 2026 Charles Liang）sim/pre_tuning_dialog.py、sim/prompt_context.py：
用户偏好整理成结构化上下文（goal_priority / aggressiveness / hard_constraints / max_overshoot_percent / known_notes），
“显式用户偏好优先于默认调参启发式”。区别：原版靠大模型把自由文本整理成 JSON；这里固定问题 + 规则解析，
不依赖大模型（离线规则助手也能用），解析结果交给人在对话框里确认后才生效。
生效方式：①写进 Agent 上下文（工作台通知）；②护栏收紧——超调上限压低 good-enough、目标选打分权重、保守档单步上限 ≤20%。
只会收紧护栏，不会放宽。"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

PLANTS = {"speed": "速度环（电机转速）", "position": "位置环（舵机/云台/电机角度）", "balance": "平衡（倒立摆/平衡车）",
          "ball": "钢球/板球", "track": "循迹/视觉跟踪（方向环）", "temp": "温度", "other": "其他"}
ACTUATORS = {"dc_pwm": "直流电机 + H 桥 PWM", "servo": "舵机", "stepper": "步进电机", "bldc": "无刷 / FOC 驱动",
             "heater": "加热片 / 继电器", "other": "其他"}
GOALS = {"balanced": "均衡", "conservative": "稳为主（怕超调/振荡）", "actuator": "护执行器（少来回换向）"}
AGGR = {"conservative": "保守（每步小改）", "normal": "正常"}

QUESTIONS = [
    {"key": "plant", "q": "控制对象是什么？", "choices": PLANTS},
    {"key": "actuator", "q": "执行器是什么？", "choices": ACTUATORS},
    {"key": "max_overshoot_pct", "q": "能接受的最大超调（%，空 = 默认 10%）", "type": "number"},
    {"key": "output_limit", "q": "输出安全限（例如 PWM ≤ 60%、舵机 30°..150°；空 = 按固件限幅）", "type": "text"},
    {"key": "goal", "q": "目标侧重", "choices": GOALS},
    {"key": "aggressiveness", "q": "调参步子", "choices": AGGR},
    {"key": "notes", "q": "还有什么不能接受的情况或已知特性？（自由填写，规则会从里面认超调上限、不能反转等）", "type": "text"},
]

# 对象 → 默认目标（用户没选时）：钢球/平衡怕超调，舵机护执行器
DEFAULT_GOAL = {"ball": "conservative", "balance": "conservative", "position": "actuator"}


@dataclass
class PreTune:
    plant: str = "other"
    actuator: str = "other"
    max_overshoot_pct: float | None = None
    output_limit: str = ""
    goal: str = ""
    aggressiveness: str = "normal"
    notes: str = ""
    hard_constraints: list = field(default_factory=list)

    def effective_goal(self) -> str:
        return self.goal if self.goal in GOALS else DEFAULT_GOAL.get(self.plant, "balanced")

    def summary(self) -> str:
        parts = [f"对象：{PLANTS.get(self.plant, self.plant)}", f"执行器：{ACTUATORS.get(self.actuator, self.actuator)}",
                 f"目标：{GOALS[self.effective_goal()]}", f"步子：{AGGR.get(self.aggressiveness, self.aggressiveness)}"]
        if self.max_overshoot_pct is not None:
            parts.append(f"超调 ≤ {self.max_overshoot_pct:g}%")
        if self.output_limit:
            parts.append(f"输出限：{self.output_limit}")
        if self.hard_constraints:
            parts.append("硬约束：" + "；".join(self.hard_constraints))
        return "，".join(parts)

    def prompt_text(self) -> str:
        return ("调参前问答（用户亲自确认的偏好，优先级高于默认调参启发式；硬约束不能违反，违反就回复 OBSERVE 并说明）："
                + self.summary() + (f"。用户补充：{self.notes}" if self.notes else ""))

    def apply(self, guard) -> list[str]:
        """只收紧护栏；返回改了什么（给界面显示）。"""
        out = []
        if self.max_overshoot_pct is not None and self.max_overshoot_pct < guard.good["overshoot_pct"]:
            guard.good["overshoot_pct"] = float(self.max_overshoot_pct); out.append(f"达标超调 ≤ {self.max_overshoot_pct:g}%")
        g = self.effective_goal()
        if guard.weights is not None and g != "balanced":
            guard.weights = g; out.append(f"打分权重 {g}")
        if self.aggressiveness == "conservative":
            r = guard.max_step_ratio
            guard.max_step_ratio = 0.2 if r is None else min(r, 0.2); out.append(f"单步 ≤ ±{guard.max_step_ratio:g}")
        return out


_NEG = re.compile(r"(不能|不要|禁止|不许|别|避免|不可以)[^，。,;；\n]{1,30}")
_OVER = re.compile(r"超调[^0-9\n]{0,8}?(\d+(?:\.\d+)?)\s*%")


def parse_notes(text: str) -> dict:
    """从自由文本认出：超调上限、硬约束（“不能…/禁止…”）、目标/步子倾向。认不出就不填（不猜）。"""
    t = text or ""
    out: dict = {"hard_constraints": [m.group(0).strip() for m in _NEG.finditer(t)]}
    if m := _OVER.search(t):
        out["max_overshoot_pct"] = float(m.group(1))
    elif re.search(r"不能超调|不要超调|零超调|无超调", t):
        out["max_overshoot_pct"] = 2.0
    if re.search(r"保守|慢慢|小步|别太猛", t):
        out["aggressiveness"] = "conservative"
    if re.search(r"振荡|抖|来回|换向", t):
        out["goal"] = "actuator"
    elif re.search(r"稳|平滑|不能超调|零超调", t):
        out["goal"] = "conservative"
    return out


def from_answers(ans: dict) -> PreTune:
    """界面表单 → PreTune。自由文本里认出来的只在用户没显式选时补上（显式选择优先）。"""
    a = {k: v for k, v in (ans or {}).items() if v not in (None, "")}
    p = parse_notes(str(a.get("notes", "")))
    mo = a.get("max_overshoot_pct", p.get("max_overshoot_pct"))
    try:
        mo = None if mo is None else max(0.0, min(100.0, float(mo)))
    except (TypeError, ValueError):
        mo = None
    return PreTune(plant=a.get("plant", "other") if a.get("plant") in PLANTS else "other",
                   actuator=a.get("actuator", "other") if a.get("actuator") in ACTUATORS else "other",
                   max_overshoot_pct=mo, output_limit=str(a.get("output_limit", ""))[:200],
                   goal=a.get("goal") if a.get("goal") in GOALS else p.get("goal", ""),
                   aggressiveness=a.get("aggressiveness") if a.get("aggressiveness") in AGGR else p.get("aggressiveness", "normal"),
                   notes=str(a.get("notes", ""))[:500], hard_constraints=p["hard_constraints"])


def to_dict(pt: PreTune | None) -> dict | None:
    return None if pt is None else asdict(pt) | {"summary": pt.summary(), "effective_goal": pt.effective_goal()}
