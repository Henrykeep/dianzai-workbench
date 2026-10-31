"""#109 / #129：阶跃幅度是否超过声明的单步上限——iterate_start（iterate_plan）和降幅卡的 retest_blocked_by 共用这一个判定。"""
from __future__ import annotations


def step_block(target, max_step, ch: int = 0, unit: str | None = None) -> dict | None:
    """超过 link.step[ch].max_step → {reason, limit, limit_unit, limit_name, message_zh, fix_action}；否则 None。"""
    if target is None or max_step is None or not abs(float(target)) > float(max_step):
        return None
    t, m = float(target), float(max_step)
    u = unit or ""
    return {"reason": "step_too_large", "limit": m, "limit_unit": unit or None, "limit_name": f"link.step[{int(ch)}].max_step",
            "message_zh": f"题面幅度 {abs(t):g}{u} 超过声明的单步上限 {m:g}{u}，需先在声明里放宽 max_step 或确认执行器能承受",
            "fix_action": "edit_declaration"}
