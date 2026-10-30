"""阶跃辨识与稳态判定——暂不可用。

原实现是 GPL-3.0 代码（third_party/vendored/pid_helper），按许可规则已从仓库删除；净室重写前这里只给诚实的报错：
- steady_state 返回 reason="unavailable"（steady=False），调用方照常走，只是没有“还没稳”提示；
- open_loop_pid 抛 IdentError（中文原因）。
"""
from __future__ import annotations


class IdentError(ValueError):
    """辨识失败（带中文原因）。"""


UNAVAILABLE = "阶跃辨识/稳态判定暂不可用：原 GPL 实现已删除，净室重写中"
REASONS = {"unavailable": "稳态判定暂不可用（原 GPL 实现已删除）"}


def samples(t, y, u=None):
    u = u or [0.0] * len(y)
    return [{"t": a * 1000.0, "actual": float(b), "input": float(c)} for a, b, c in zip(t, y, u)]


def steady_state(t, y, t_step=None, window_s=0.3, warmup_s=0.2, span_ref=None) -> dict:
    return {"steady": False, "reason": "unavailable", "text": REASONS["unavailable"], "noise": 0.0, "drift": 0.0, "amplitude": 0.0}


def open_loop_pid(t, y, t_step, du, u=None, base_s=0.35, tail_s=0.7, min_change=0.0) -> dict:
    raise IdentError(UNAVAILABLE)
