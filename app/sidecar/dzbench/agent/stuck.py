"""卡死检测：Agent 在原地打转时提醒一次，再转就停下交给人。

Source: github.com/OpenHands/software-agent-sdk@47bbc5e openhands-sdk/openhands/sdk/conversation/stuck_detector.py
License: MIT（Copyright (c) 2026 OpenHands contributors）。
改动：事件模型换成 OpenAI 格式的 messages（assistant.tool_calls = 动作，tool = 观察，ok=false = 错误）；
四种模式与阈值照搬（同动作同结果 4 次、同动作同报错 >3 次、连续 3 条自言自语、ABAB 交替 6 次）；
原版 context-window 模式是 TODO，没搬。另加：同动作同结果第 3 次时先提醒一次（原 REPEAT_WARN 的位置）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .untrusted import unwrap

SCAN = 20                 # 只看最近这么多个事件（原 MAX_EVENTS_TO_SCAN_FOR_STUCK_DETECTION）


@dataclass
class Thresholds:         # 原 StuckDetectionThresholds 的默认值
    action_observation: int = 4
    action_error: int = 3
    monologue: int = 3
    alternating_pattern: int = 6


@dataclass(frozen=True)
class Ev:
    kind: str             # action / obs / error / agent_msg / user
    key: str              # 用于比较相等（去掉 id）
    tool: str = ""


def events(messages: list[dict]) -> list[Ev]:
    """messages → 最后一条真用户消息之后的事件。'[工作台' 开头的 user 消息是工作台自己的提醒，不算用户打断。"""
    out: list[Ev] = []
    for m in messages:
        r = m.get("role")
        if r == "user":
            c = m.get("content") or ""
            if not str(c).startswith("[工作台"):
                out = []
        elif r == "assistant":
            calls = m.get("tool_calls") or []
            if not calls:
                out.append(Ev("agent_msg", m.get("content") or ""))
            for c in calls:
                f = c.get("function", {})
                try:
                    args = json.dumps(json.loads(f.get("arguments") or "{}"), sort_keys=True, ensure_ascii=False)
                except ValueError:
                    args = f.get("arguments") or ""
                out.append(Ev("action", f"{f.get('name')}|{args}", f.get("name", "")))
        elif r == "tool":
            c = unwrap((m.get("content") or "").split("\n[工作台")[0])
            ok = True
            try:
                ok = bool(json.loads(c).get("ok", True))
            except (ValueError, AttributeError):
                pass
            out.append(Ev("obs" if ok else "error", c))
    return out[-SCAN:]


class StuckDetector:
    def __init__(self, thresholds: Thresholds | None = None):
        self.t = thresholds or Thresholds()
        self._nudged: set[tuple] = set()

    @staticmethod
    def _last(evs, n):
        acts = [e for e in reversed(evs) if e.kind == "action"][:n]
        obs = [e for e in reversed(evs) if e.kind in ("obs", "error")][:n]
        return acts, obs

    def _streak(self, evs, kinds) -> int:
        acts, obs = self._last(evs, SCAN)
        if not acts or not obs:
            return 0
        k = 0
        for a, o in zip(acts, obs):
            if a != acts[0] or o.kind not in kinds or (kinds == ("obs",) and o != obs[0]):
                break
            k += 1
        return k

    def check(self, messages: list[dict]) -> str | None:
        """卡住了 → 返回原因（给人看）；没卡住 → None。"""
        evs = events(messages)
        t = self.t
        if self._streak(evs, ("obs",)) >= t.action_observation:
            return f"同一个工具用相同参数调用了 {t.action_observation} 次，结果都一样"
        if self._streak(evs, ("error",)) > t.action_error:
            return f"同一个工具用相同参数连续报错超过 {t.action_error} 次"
        mono = 0
        for e in reversed(evs):
            if e.kind != "agent_msg":
                break
            mono += 1
        if mono >= t.monologue:
            return f"连续 {mono} 条回答没有调用工具也没有用户输入（自言自语）"
        n = t.alternating_pattern
        acts, obs = self._last(evs, n)
        if len(acts) == n and len(obs) == n and all(acts[i] == acts[i + 2] for i in range(n - 2)) \
                and all(obs[i] == obs[i + 2] for i in range(n - 2)) and acts[0] != acts[1]:
            return f"在两个动作之间来回切换了 {n // 2} 轮，结果没有变化"
        return None

    def nudge(self, messages: list[dict]) -> str | None:
        """快卡住时提醒一次（每段连击只提醒一次）：同动作同报错第 3 次（原版 get_action_error_nudge）、同动作同结果第 3 次。"""
        evs = events(messages)
        acts, obs = self._last(evs, 1)
        if not acts:
            return None
        e = self._streak(evs, ("error",))
        s = self._streak(evs, ("obs",))
        tag = (acts[0], obs[0] if obs else None)
        if e == self.t.action_error and ("e",) + tag not in self._nudged:
            self._nudged.add(("e",) + tag)
            return (f"你已经用相同参数调用 {acts[0].tool} {e} 次，每次都是同样的错误。再原样调用不会有用——"
                    "先读错误信息，改参数或换做法。")
        if s == self.t.action_observation - 1 and ("s",) + tag not in self._nudged:
            self._nudged.add(("s",) + tag)
            return f"这是第 {s} 次用相同参数调用 {acts[0].tool}，结果不会变。请先分析上面的结果，换个做法或直接回答。"
        return None
