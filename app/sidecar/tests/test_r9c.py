"""r9c 回归：#93 换算出处、#75/#92 唯一有效性来源、#94 iterate_start 单独跑与主线同一条路。"""
from __future__ import annotations


import pytest
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


class DeadIO(MockIO):
    """对象完全不响应：每轮都 no_rise。"""
    def step(self, it, ch, target, dur_ms):
        self.calls.append(dur_ms)
        return dzstep.decode_step_result(result_bytes(it, I.params_hash(self.order(), self.v), settle=0, rise=None))


@pytest.mark.parametrize("cap,expect", [(None, [2000, 4000, 8000, 12000]), (5000, [2000, 4000, 5000])])
def test_unresponsive_plant_hits_hard_cap(cap, expect):
    io, ev = DeadIO(), []
    out = I.Iterator(io, dict(PLAN, dur_ms=2000, max_step_dur_ms=cap), True, emit=ev.append).run()
    assert out["reason"] == "plant_unresponsive" and out["best"] is None and "round0" not in out, out
    assert io.calls == expect and getattr(io, "output_stopped", False)
    if cap is None:                                  # 没声明：卡上明说用默认 12 s，并指到声明字段
        assert out["dur_cap_notice_zh"] == "未声明阶跃时长上限，使用默认 12 s"
        assert out["fix_action"] == "edit_declaration" and out["fix_field"] == "link.step.max_step_dur_ms"
    else:
        assert "dur_cap_notice_zh" not in out and "fix_action" not in out
    assert S.AgentService._verdict({"inside": True}, out, None)[0] == "unknown"
    from dzbench.agent.reason_codes import table
    t = table()["plant_unresponsive"]
    assert t["message_zh"] == "对象无响应" and t["causes"] == ["没上电", "接线", "方向（执行器 / 传感器极性接反）", "执行器饱和"]


@pytest.mark.needs_sim
@pytest.mark.parametrize("seed", [3, 3010])
def test_direct_iterate_start_and_main_flow_use_same_plan(seed, home):
    """直接 iterate_start 与主流程（默认目标）用同一份计划。以前这里用 SimpleNamespace 假服务 + 返回空 dict 的假 measure_step_timing（替身），
    现在走真 randplant 对象 → 真 host-sim 仿真板 → 真 Session + AgentService + 真 measure_step_timing。"""
    import pathlib as _pl
    import sys as _sys
    import time as _t
    _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[3] / "tools"))
    import randplant
    from dzbench import paths
    from dzbench.agent_api import AgentTools
    from dzbench.session import Session
    p = randplant.gen(seed)
    p["name"] = f"same-plan-{seed}"
    randplant.write(p, paths.projects_dir() / p["name"])
    s = Session()
    s.connect(f"sim:{p['name']}")
    try:
        t0 = _t.monotonic()
        while _t.monotonic() - t0 < 60 and not (s.schema and len(s.window(0.5)) > 5):
            _t.sleep(0.05)
        assert s.schema and s.schema.step, "仿真板起不来 / 没握手"
        svc = S.AgentService(s, AgentTools(s, lambda e: None), lambda e: None)
        main = svc.iterate_plan(_default_target=True)
        direct = svc.iterate_plan(target=main["target"])
        core = ("ch", "target", "dur_ms", "abs_tol", "params")      # 退默认的说明（fallback / message_zh）各自写明自己退了什么
        assert {k: main[k] for k in core} == {k: direct[k] for k in core}
        o = svc.measure_step_timing()                               # 按端口缓存：就是 iterate_plan 用的那一次
        if o.get("step_target") is None:
            assert "span_quarter" in main["fallback"] and main["fix_action"] == "measure_step_timing", main
        else:
            assert main["target"] == pytest.approx(float(o["step_target"]))
    finally:
        s.disconnect()


@pytest.mark.parametrize("cache,vs_board,expect", [(True, False, "clear_schema_cache"), (False, False, "build"), (False, True, "reflash")])
def test_schema_conflict_fix_action_by_kind(tmp_path, monkeypatch, cache, vs_board, expect):
    """schema_conflict 的修法按种类：有缓存拷贝 → clear_schema_cache；只有编译产物互冲 → build；编译产物对板子 → reflash。
    进度阻塞项（progress.blockers）用同一个 fix_action，不再一律 clear_schema_cache。"""
    from dzbench import progress, schema
    monkeypatch.setattr(schema, "cache_dir", lambda: tmp_path / "cache")
    p1 = (tmp_path / "cache" if cache else tmp_path / "build") / "a.json"
    e = schema.SchemaConflict(0x1234ABCD, [str(p1), str(tmp_path / "build2/b.json")], None, vs_board=vs_board)
    d = e.as_dict()
    assert d["fix_action"] == expect and d["fix_zh"]
    bl = [b for b in progress.blockers({"link": {"board": "connected"}, "schema_conflict": d}) if b["code"] == "schema_conflict"]
    assert bl and bl[0]["fix_action"] == expect and bl[0]["fix_zh"] == d["fix"]
