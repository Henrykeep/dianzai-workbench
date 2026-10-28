"""Agent 对话循环：LLM 只能调用这里登记的工具；写操作全部变成待确认的提议/改动卡片。"""
from __future__ import annotations

import json
from typing import Callable

from .gateway import FORBIDDEN_TOOLS, GatewayError
from .llm import LLMError

SYSTEM = """你是“电赛工作台”内置调参与代码助手，用户是正在比赛现场调车的学生。
规则：
1. 先用 read_telemetry / step_analysis / list_params 看数据，再下结论；结论要引用具体数字。
2. 改板上参数只能用 propose_param_change（用户确认后才生效，网关会限幅）；一次只改 1~2 个参数，步子小。
3. 改代码/配置只能用 propose_edit（SEARCH/REPLACE，search 必须唯一）；firmware/ ports/ tools/ 是冻结层，不要尝试。
4. 你无权、也不应触发或解除急停；涉及安全的问题直接提醒用户断电。
5. 回答用中文，简短，先给结论和下一步。
6. 调参：先 tune_context 看指标/关键样本/历史表；每轮只改一个参数，证据最充分的那个；证据不足就调 observe；
   历史表里 last_rejected 的方向不要重复；改完用 run_step_test 实测。是否达标、要不要回滚由程序判定，你说 DONE 只是建议。
7. 烧录 / 实机阶跃 / 实机回滚会变成待用户点击的动作卡，不会立即执行；烧录默认 dry-run。
8. 区分事实与推断：来自工具/数据/源码的标【实测】或【源码】，自己的判断标【推断】；没看过的文件不要说"代码里是这样"。
9. 不覆盖用户没提交的改动：propose_edit 前先 read_file 看当前内容，只改需要的最小片段。
10. 实验结论看 verdict：steady.reason 是 warming_up/still_drifting 时先 observe 或加长实验，不要据此改参数；asymmetry 显示上下不对称时优先建议前馈/静摩擦补偿，而不是硬拧 PID。
11. 结束时列出"待实板确认"的事项（仿真通过 ≠ 实机通过）。"""

TOOLS = [
    {"name": "read_telemetry", "description": "最近 seconds 秒每个通道的 min/max/mean/last",
     "input_schema": {"type": "object", "properties": {"seconds": {"type": "number"}}}},
    {"name": "list_params", "description": "板上参数：名称、当前值、范围、单位、说明", "input_schema": {"type": "object", "properties": {}}},
    {"name": "step_analysis", "description": "对最近一次设定值阶跃算超调/上升/调节/稳态误差/振荡，并给规则建议",
     "input_schema": {"type": "object", "required": ["y", "sp"], "properties": {
         "y": {"type": "string", "description": "反馈通道名"}, "sp": {"type": "string", "description": "设定值通道名"},
         "seconds": {"type": "number"}, "kp": {"type": "string"}, "ki": {"type": "string"}, "kd": {"type": "string"}}}},
    {"name": "propose_param_change", "description": "提议改一个板上参数（需用户确认）",
     "input_schema": {"type": "object", "required": ["name", "value", "reason"], "properties": {
         "name": {"type": "string"}, "value": {"type": "number"}, "reason": {"type": "string"}}}},
    {"name": "list_files", "description": "列出仓库文件（glob）", "input_schema": {"type": "object", "properties": {"glob": {"type": "string"}}}},
    {"name": "read_file", "description": "读仓库文件", "input_schema": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}},
    {"name": "propose_edit", "description": "提议修改仓库文件（SEARCH/REPLACE；用户看 diff 确认，通过 make check 后自动 git 提交）",
     "input_schema": {"type": "object", "required": ["path", "search", "replace", "reason"], "properties": {
         "path": {"type": "string"}, "search": {"type": "string"}, "replace": {"type": "string"}, "reason": {"type": "string"}}}},
    {"name": "tune_context", "description": "调参上下文：阶跃指标、约 20 个关键样本、带 best/last_rejected 标签的历史表、护栏规则",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "observe", "description": "证据不足：本轮保持参数不变", "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}}},
    {"name": "run_step_test", "description": "按工程配置做一次标准阶跃实验并由程序判定 continue/done/rollback/stop（实机需用户点击）",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "rollback_best", "description": "回滚到历史最好的一组增益（实机需用户点击）", "input_schema": {"type": "object", "properties": {}}},
    {"name": "flash", "description": "烧录最近一次编译的镜像（前置条件检查；默认 dry_run；需用户点击）",
     "input_schema": {"type": "object", "properties": {"dry_run": {"type": "boolean"}}}},
    {"name": "build_log", "description": "解析 Keil 编译日志为错误/警告列表和程序大小", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}}},
    {"name": "decode_hardfault", "description": "解码 HardFault 栈帧（按内核：M0+ 无 CFSR）",
     "input_schema": {"type": "object", "required": ["frame"], "properties": {"frame": {"type": "array", "items": {"type": "integer"}},
                      "exc_return": {"type": "integer"}, "regs": {"type": "object"}}}},
    {"name": "read_symbol", "description": "查 ELF 里变量/函数的地址和大小", "input_schema": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}},
]
assert not any(f in t["name"] for t in TOOLS for f in FORBIDDEN_TOOLS)


TOOL_MAX = 16_000   # 回给模型的单条工具结果上限（字符）


def tool_content(res: dict) -> str:
    """工具结果转 JSON；超长时只截断文本本身，保证仍是合法 JSON（以前直接切字符串，16 KB 的 project.yaml 就读不出来）。"""
    out = json.dumps(res, ensure_ascii=False, default=str)
    if len(out) <= TOOL_MAX:
        return out
    if isinstance(res.get("result"), str):
        return json.dumps({**res, "result": res["result"][:TOOL_MAX - 200], "truncated": True}, ensure_ascii=False)
    return json.dumps({"ok": res.get("ok", False), "error": "工具结果太长被截断", "truncated": True}, ensure_ascii=False)


class AgentLoop:
    def __init__(self, llm, handlers: dict[str, Callable], emit: Callable[[dict], None] = lambda e: None, max_steps: int = 8,
                 project_rules: str = "", gate: Callable | None = None):
        self.llm, self.handlers, self.emit, self.max_steps = llm, handlers, emit, max_steps
        self.gate = gate or (lambda tool, args, run: run())
        sys_ = SYSTEM + (f"\n\n以下是本工程仓库的 AGENTS.md（项目规则，必须遵守）：\n{project_rules[:6000]}" if project_rules else "")
        self.messages: list[dict] = [{"role": "system", "content": sys_}]

    def reset(self) -> None:
        self.messages = self.messages[:1]

    def ask(self, text: str) -> str:
        self.messages.append({"role": "user", "content": text})
        for _ in range(self.max_steps):
            try:
                m = self.llm.chat(self.messages, TOOLS)
            except LLMError:
                if self.messages[-1]["role"] == "user":
                    self.messages.pop()
                raise
            self.messages.append({k: v for k, v in m.items() if k in ("role", "content", "tool_calls")} | {"role": "assistant"})
            calls = m.get("tool_calls") or []
            if not calls:
                return m.get("content") or ""
            for c in calls:
                name, args = c["function"]["name"], {}
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                    if name not in self.handlers or any(f in name for f in FORBIDDEN_TOOLS):
                        raise GatewayError("denied", f"没有工具 {name}")
                    res = {"ok": True, "result": self.gate(name, args, lambda: self.handlers[name](**args))}
                except (GatewayError, Exception) as e:   # noqa: BLE001 —— 工具错误回给模型，让它自己改
                    res = {"ok": False, "error": getattr(e, "message", str(e))}
                self.emit({"type": "agent_tool", "name": name, "args": args, "ok": res["ok"]})
                self.messages.append({"role": "tool", "tool_call_id": c.get("id", name),
                                      "content": tool_content(res)})
        return "（步数用完，先停在这里。看看上面的提议卡片。）"
