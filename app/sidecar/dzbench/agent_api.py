"""给将来内置 Agent 的工具层（接缝，MVP 不含 Agent 本体）。

原则：Agent 只能“读”和“提议”；任何写参数都变成一张提议卡片，必须由人在 UI 上点“采纳”才下发，
走与手动修改完全相同的路径（限幅、ACK、日志）。急停永远只属于人。
工具描述用 JSON Schema，可直接映射成 MCP / function-calling 的 tool 定义。
"""
from __future__ import annotations

import itertools
import statistics
import threading

from .session import LinkError, Session

TOOLS = [
    {"name": "read_telemetry", "description": "最近 seconds 秒的遥测统计（每通道 min/max/mean/last）",
     "input_schema": {"type": "object", "properties": {"seconds": {"type": "number", "default": 2}}}},
    {"name": "list_params", "description": "参数表：名称、当前值、范围、单位、说明",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "propose_param_change", "description": "提议修改一个参数；需用户在界面确认后才生效",
     "input_schema": {"type": "object", "required": ["name", "value", "reason"],
                      "properties": {"name": {"type": "string"}, "value": {"type": "number"}, "reason": {"type": "string"}}}},
]


class AgentTools:
    def __init__(self, session: Session, emit):
        self.s, self.emit = session, emit
        self.pending: dict[int, dict] = {}
        self._ids = itertools.count(1)
        self.lock = threading.Lock()
        self.on_apply = None          # AgentService 挂上：Agent 的提议落地后记日志（可撤销）

    def read_telemetry(self, seconds: float = 2.0) -> dict:
        w = self.s.window(seconds)
        if not w:
            return {"n": 0}
        out = {"n": len(w), "seconds": round(w[-1][0] - w[0][0], 3)}
        for k in w[0][1]:
            ys = [v[k] for _, v in w]
            out[k] = {"min": min(ys), "max": max(ys), "mean": statistics.fmean(ys), "last": ys[-1]}
        return out

    def list_params(self) -> list[dict]:
        if not self.s.schema:
            return []
        return [{**{k: p[k] for k in ("name", "min", "max", "unit", "desc", "default") if k in p},
                 "value": self.s.params.get(p["name"])} for p in self.s.schema.params]

    def propose_param_change(self, name: str, value: float, reason: str, source: str = "agent") -> dict:
        if not self.s.schema or name not in self.s.schema.param_index:
            raise LinkError("bad_param", f"没有参数 {name}")
        v, clamped = self.s.schema.clamp(name, float(value))
        with self.lock:
            pid = next(self._ids)
            p = {"type": "proposal", "id": pid, "name": name, "value": v, "clamped": clamped,
                 "current": self.s.params.get(name), "reason": reason, "source": source}
            self.pending[pid] = p
        self.emit(p)
        return {"id": pid, "status": "pending_user_confirmation"}

    def decide(self, pid: int, accept: bool) -> dict:
        with self.lock:
            p = self.pending.pop(pid, None)
        if not p:
            raise LinkError("no_proposal", f"提议 {pid} 不存在或已处理")
        if not accept:
            return {"id": pid, "status": "rejected"}
        r = {"id": pid, "status": "applied", **self.s.set_param(p["name"], p["value"])}
        if self.on_apply:
            self.on_apply(p, r)
        return r

    def call(self, tool: str, args: dict):
        if tool not in {t["name"] for t in TOOLS}:
            raise LinkError("bad_tool", f"未知工具 {tool}")
        return getattr(self, tool)(**args)
