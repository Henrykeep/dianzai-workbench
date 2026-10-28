"""把 tuning / gateway / llm / loop 组装到一个会话上，供 server 调用（也方便测试时注入假 LLM）。"""
from __future__ import annotations

import re

from ..agent_api import AgentTools
from ..session import LinkError, Session
from ..transport import ROOT
from . import llm as llm_mod
from . import yamlpar
from .gateway import Gateway, GatewayError
from .loop import AgentLoop
from .tuning import step_metrics, tuning_hints


def guess_pairs(fields: list[str]) -> list[tuple[str, str]]:
    """猜 (反馈, 设定) 通道对：sp_a↔spd_a、ball_sp_px↔cam_x_px 之类靠后缀/同名去掉 sp。"""
    out = []
    for sp in fields:
        if not re.search(r"(^|_)(sp|set|target|ref)(_|$)", sp):
            continue
        key = re.sub(r"(^|_)(sp|set|target|ref)(_|$)", r"\1", sp).strip("_")
        cands = [f for f in fields if f != sp and (f.endswith("_" + key) or f.startswith(key + "_") or key and key in f)]
        if cands:
            out.append((sorted(cands, key=len)[0], sp))
    return out


def guess_gain(params: list[str], kind: str) -> str | None:
    for p in params:
        if p == kind or p.endswith("_" + kind):
            return p
    return None


class AgentService:
    def __init__(self, session: Session, tools: AgentTools, emit, root=ROOT, llm=None, runner=None):
        self.s, self.tools, self.emit = session, tools, emit
        self.gw = Gateway(root, emit, **({"runner": runner} if runner else {}))
        self._llm = llm
        self.loop = AgentLoop(None, {
            "read_telemetry": tools.read_telemetry,
            "list_params": tools.list_params,
            "step_analysis": self.step_analysis,
            "propose_param_change": lambda name, value, reason: tools.propose_param_change(name, value, reason, "agent"),
            "list_files": lambda glob="**/*": self.gw.list_files(glob),
            "read_file": lambda path: self.gw.read_file(path),
            "propose_edit": lambda path, search, replace, reason: self.gw.propose_edit(path, search, replace, reason, "agent"),
        }, emit)

    # -------------------------------------------------------------- 离线调参
    def step_analysis(self, y: str | None = None, sp: str | None = None, seconds: float = 5.0,
                      kp: str | None = None, ki: str | None = None, kd: str | None = None) -> dict:
        w = self.s.window(seconds)
        if not w:
            raise LinkError("no_data", "还没有遥测数据", "先连接板子（或仿真板）并给一个阶跃")
        fields = list(w[0][1])
        if not (y and sp):
            pairs = guess_pairs(fields)
            if not pairs:
                raise LinkError("no_pair", "认不出哪路是设定值、哪路是反馈", "在下拉框里手动选反馈和设定通道")
            y, sp = pairs[0]
        for f in (y, sp):
            if f not in fields:
                raise LinkError("bad_field", f"没有通道 {f}")
        names = [p["name"] for p in (self.s.schema.params if self.s.schema else [])]
        kp, ki, kd = kp or guess_gain(names, "kp"), ki or guess_gain(names, "ki"), kd or guess_gain(names, "kd")
        m = step_metrics([t for t, _ in w], [float(v[y]) for _, v in w], [float(v[sp]) for _, v in w])
        gains = {k: self.s.params[k] for k in (kp, ki, kd) if k and k in self.s.params}
        hints = tuning_hints(m, gains, kp or "kp", ki, kd)
        return {"y": y, "sp": sp, "pairs": guess_pairs(fields), "gains": {"kp": kp, "ki": ki, "kd": kd},
                "metrics": m.as_dict(), "hints": [h.as_dict() for h in hints]}

    def propose_hint(self, changes: dict, reason: str) -> list[dict]:
        return [self.tools.propose_param_change(k, v, reason, "规则") for k, v in changes.items()]

    # -------------------------------------------------------------- 写回 yaml
    def yaml_target(self) -> str:
        names = {p["name"] for p in self.s.schema.params} if self.s.schema else set()
        if not names:
            raise LinkError("no_schema", "还没识别出参数表")
        for f in yamlpar.param_files(self.gw.root):
            txt = f.read_text(encoding="utf-8")
            if all(re.search(rf"\bname:\s*{re.escape(n)}\b", txt) for n in names):
                return f.relative_to(self.gw.root).as_posix()
        raise LinkError("no_yaml", "仓库里找不到包含这组参数的 app.yaml / project.yaml", "确认工作台仓库与板上固件是同一个工程")

    def yaml_writeback(self, path: str | None = None, values: dict | None = None) -> dict:
        path = path or self.yaml_target()
        values = values if values is not None else dict(self.s.params)
        return self.gw.propose_yaml_params(path, values, "把当前板上调好的参数写回为默认值", "user")

    # -------------------------------------------------------------- LLM
    def llm(self):
        return self._llm or llm_mod.OpenAICompat()

    def ask(self, text: str) -> str:
        self.loop.llm = self.llm()
        try:
            return self.loop.ask(text)
        except llm_mod.LLMError as e:
            raise LinkError("llm", e.message, e.fix) from e


__all__ = ["AgentService", "GatewayError", "guess_pairs"]
