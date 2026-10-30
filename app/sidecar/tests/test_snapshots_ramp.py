"""平滑切换预设的插值计划（纯函数）。"""
from dzbench.snapshots import ramp_plan


def test_ramp_linear_and_exact_end():
    plan = ramp_plan({"kp": 1.0, "ki": 0.0}, {"kp": 2.0, "ki": 0.0}, 4)
    assert [st["kp"] for st in plan] == [1.25, 1.5, 1.75, 2.0]
    assert all("ki" not in st for st in plan)               # 不变的参数不发


def test_ramp_unknown_current_written_at_end_and_noop():
    plan = ramp_plan({"kp": None}, {"kp": 3.0}, 5)
    assert plan == [{"kp": 3.0}]
    assert ramp_plan({"kp": 1.0}, {"kp": 1.0}, 5) == []
    assert ramp_plan({"kp": 0.0}, {"kp": 1.0}, 0) == [{"kp": 1.0}]
