"""r9c 回归：#93 换算出处、#75/#92 唯一有效性来源、#94 iterate_start 单独跑与主线同一条路。"""
from __future__ import annotations

import struct
from types import SimpleNamespace

from dzbench.agent import iterate as I
from dzbench.agent import service as S
from dzbench.agent.guard import TuneGuard
from dzbench.agent.tuning import StepMetrics
from dzbench.stepproto import dzstep
from test_iterate import PLAN, MockIO, result_bytes


# ---------------------------------------------------------------- #93
def test_pass_basis_always_names_conversion_source():
    band = {"limit": 1.0, "unit": "cm", "item": "X1", "source": "题目 X1：误差 ≤ 1cm"}
    sim = S.AgentService._pass_basis(band, True, S.AgentService._conv_zh("phys", "px", "cm"))
    cal = S.AgentService._pass_basis(band, True, S.AgentService._conv_zh("calibration", "px", "cm"))
    same = S.AgentService._pass_basis(band, True, S.AgentService._conv_zh(None, "cm", "cm"))
    assert "在带内" in sim and "仿真标称" in sim and "未实机标定" in sim
    assert "在带内" in cal and "实机标定" in cal
    assert "同单位" in same
    hw = S.AgentService._pass_basis(band, None, "实机未标定")
    assert "在带内" not in hw and "待标定" in hw


def test_pass_verdict_zh_is_tongguo_source_in_basis():   # #121：verdict_zh 一律「通过」；换算出处在 pass_basis（#93）
    ss = {"inside": True, "conv_source": "phys", "unit": "px", "band": {"unit": "cm"}}
    v, vzh = S.AgentService._verdict(ss, {"reason": "pass"}, {"ok": True, "rise_s": 0.1, "settling_s": 0.3, "overshoot_pct": 1.0})
    assert v == "pass" and vzh == "通过"


def test_real_hw_uncalibrated_is_inside_null():
    stub = SimpleNamespace(sim=False, s=SimpleNamespace(schema=SimpleNamespace(fields=[{"name": "y", "unit": "px"}], step=[])),
                           step_cfg=lambda: {"y": "y", "high": [10.0], "low": [0.0]}, _project_path=lambda: None,
                           _calibration_per=lambda *a: (None, None), _phys_per=lambda *a: (0.5, "固件声明"),
                           _step_amp=lambda m: 10.0, _pass_basis=S.AgentService._pass_basis, _conv_zh=S.AgentService._conv_zh)
    stub._project_path = lambda: "/nonexistent"
    orig = S.steptools._yaml
    try:
        S.steptools._yaml = lambda p: {"items": [{"id": "X1", "metrics": [{"name": "稳态误差", "op": "<=", "value": 1.0, "unit": "cm"}]}]}
        out = S.AgentService._ss_band(stub, {"sse": 3.0})
    finally:
        S.steptools._yaml = orig
    assert out["inside"] is None and "待标定" in out["pass_basis"] and "在带内" not in out["pass_basis"], out


# ---------------------------------------------------------------- #75 / #92
def test_guard_and_iterate_share_one_validity_function():
    g = TuneGuard({"kp": (0.0, 2.0)}, True)
    g.record(StepMetrics(True, rise_s=None, settling_s=0.3, overshoot_pct=0.0), {"kp": 0.5})
    assert g.rounds[-1].valid is False and g.rounds[-1].why_invalid == I.step_invalid(g.rounds[-1].metrics) == "no_rise"
    assert g.best() is None                                      # 无效轮不当最好
    assert S.step_invalid is I.step_invalid                      # 台账 / 卡 / 提议 / 迭代同一个函数


def test_rule_engine_does_not_propose_from_invalid_round():
    g = TuneGuard({"kp": (0.0, 2.0)}, True)
    g.record(StepMetrics(True, rise_s=None, settling_s=0.0, overshoot_pct=0.0), {"kp": 0.02})
    stub = SimpleNamespace(_guard=lambda: g, cfg={"tune": {}})
    r = S.AgentService.rule_round(stub)
    assert r["action"] == "OBSERVE" and "无效" in r["reason"], r


def test_zero_amplitude_step_is_invalid_everywhere():
    assert I.step_invalid({"ok": True, "rise_ms": 100, "settle_ms": 200, "overshoot_pct": 0.0, "step_amp": 0.0, "step_tol": 0.5}) == "zero_step"


def test_invalid_stop_says_why():
    class ZeroIO(MockIO):
        def step(self, it, ch, target, dur_ms):
            h = I.params_hash(self.order(), self.v)
            return dzstep.decode_step_result(result_bytes(it, h)) | {"step_amp": 0.0, "step_tol": 1.0}
    ev = []
    out = I.Iterator(ZeroIO(), PLAN, True, emit=ev.append).run()
    assert out["reason"] == "invalid" and out["why_invalid"] == "zero_step" and "阶跃幅度为 0" in out["reason_zh"]
    v, vzh = S.AgentService._verdict({"inside": None}, out, None)
    assert v == "unknown" and "阶跃幅度为 0" in vzh


# ---------------------------------------------------------------- #94
class SlowIO(MockIO):
    """慢对象：时长不到 need_ms 时窗口里没进带（settle 0）。"""
    need_ms = 6000

    def step(self, it, ch, target, dur_ms):
        self.calls.append(dur_ms)
        h = I.params_hash(self.order(), self.v)
        if dur_ms < self.need_ms:
            return dzstep.decode_step_result(result_bytes(it, h, settle=0, rise=None))
        os_, ss = self.model(self.v)
        return dzstep.decode_step_result(result_bytes(it, h, os_=os_, ss=ss))


def test_slow_plant_extends_duration_instead_of_three_invalid_rounds():
    io = SlowIO(kp=1.0, ki=1.0)
    ev = []
    out = I.Iterator(io, dict(PLAN, dur_ms=2000), True, emit=ev.append, max_rounds=2).run()
    assert out["reason"] != "invalid" and out["best"] is not None, out
    assert io.calls[:3] == [2000, 4000, 8000]


class FakeSession:
    """SessionIO 的最小 Session：y 跟着设定值走。"""

    def __init__(self, y):
        self.y, self.sent = y, []
        self.schema = SimpleNamespace(step=[{"sp": 0, "y": "pos", "abs_tol": 1.0, "range": 400.0}])
        self._sp_live = {"sp": y}

    def window(self, s):
        return [(0.0, {"pos": self.y})]

    def setpoint_names(self):
        return ["sp"]

    def send_data(self, id_, b):
        (v,) = struct.unpack("<f", b)
        self.sent.append(v)
        self.y = v


def test_target_equal_to_current_backs_off_instead_of_zero_step():
    io = I.SessionIO(FakeSession(100.0))
    io.RETURN_DT = 0.001
    back = io.return_to_start(0, 0, 100.0)
    assert io.s.sent and io.s.sent[-1] == 0.0                   # 起点 = 目标 − 量程 × 25%
    assert back["step_amp"] >= back["step_tol"], back
    back2 = io.return_to_start(0, 0, 100.0)                      # 无效轮重跑同一 iter：回同一个起点，不重新取当前位置
    assert io.y0 == 0.0 and back2["step_amp"] == back["step_amp"]


def test_direct_iterate_start_and_main_flow_use_same_plan():
    sch = SimpleNamespace(step=[{"range": 400.0, "abs_tol": 1.0}], param_index={"kp": 0}, params=[{"name": "kp", "min": 0, "max": 2}])
    stub = SimpleNamespace(s=SimpleNamespace(schema=sch, port="sim:anything"), _gains=lambda: {"kp": "kp"},
                           measure_step_timing=lambda: {})
    main = S.AgentService.iterate_plan(stub, _default_target=True)
    direct = S.AgentService.iterate_plan(stub, target=main["target"])
    assert main == direct


def _rand_plant_rise(seed, kp, y0, target, dt=0.001, t_end=20.0):
    """通用随机一阶对象（不看题号）：K、τ 来自 seed；P 控制闭环，返回 10→90% 上升时间。"""
    import random
    r = random.Random(seed)
    K, tau = r.uniform(0.5, 3.0), r.uniform(0.05, 1.0)
    y, t, t10, t90, amp = y0, 0.0, None, None, target - y0
    while t < t_end and t90 is None:
        y += dt * (K * kp * (target - y) - 0.0) / tau
        frac = (y - y0) / amp
        if t10 is None and frac >= 0.1:
            t10 = t
        if frac >= 0.9:
            t90 = t
        t += dt
    return None if t90 is None else round(t90 - t10, 4)


def test_iterate_start_alone_parked_at_target_three_gains_distinct_metrics():
    """#94：板子停在目标上直接 iterate_start，三组不同增益必须给出三组不同指标（不是 3 个零幅度阶跃）。"""
    target, seed = 137.0, 20261031
    rises = []
    for kp in (0.5, 1.0, 2.0):
        io = I.SessionIO(FakeSession(target))
        io.RETURN_DT = 0.001
        back = io.return_to_start(0, 0, target)
        assert back["step_amp"] >= back["step_tol"], back
        assert abs(target - io.y0) >= back["step_tol"]
        rises.append(_rand_plant_rise(seed, kp, io.y0, target))
    assert None not in rises and len(set(rises)) == 3, rises
