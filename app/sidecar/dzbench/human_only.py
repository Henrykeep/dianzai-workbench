"""只能由人做的操作：统一的确认校验 + 给 Agent 的跳转（human_only / goto）。

set_run_mode（切联机/脱机）和 set_cloud_enabled（比赛模式下启用云端）共用：
  * 侧车只接受界面确认卡来的 confirmed=True（`require_confirmed`）；没确认就只回 needs_confirm，什么也不改。
  * Agent 侧一律拿到 human_only + goto（界面入口），工具表 / script_ops 里不得有能执行它们的东西。
"""
from __future__ import annotations

# fix_action → 界面入口（Agent 只给跳转，不执行）
GOTO = {"precontest": "step:封箱", "enable_cloud": "settings:cloud"}
HUMAN_ONLY_KEYS = {"human_only", "goto"}


def require_confirmed(confirmed, message_zh: str) -> dict | None:
    """确认卡校验：只有界面确认卡回来的 confirmed is True 才放行；否则返回 needs_confirm 回包（调用方原样返回、不做任何修改）。"""
    if confirmed is True:
        return None
    return {"ok": False, "result": None, "needs_confirm": True, "message_zh": message_zh}


def mark(d: dict, fix_action: str) -> dict:
    """给带 human_only fix_action 的回包 / 事件补上 human_only:true 和 goto。"""
    return {**d, "fix_action": fix_action, "human_only": True, "goto": GOTO[fix_action]}
