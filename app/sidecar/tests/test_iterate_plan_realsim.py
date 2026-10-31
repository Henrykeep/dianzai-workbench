"""#107 / #109 / #94：随机对象的声明直接能起迭代。
原先 test_r9_backend 里这条用假服务（SimpleNamespace）调 iterate_plan；fix-r9c 起 iterate_plan 要真测阶跃时序，
不许给假服务补方法凑过（7cbbbae 已 revert）。这里改成真 randplant 对象 + 真 host-sim 仿真板 + 真 Session/AgentService。"""
from __future__ import annotations

import pathlib
import time

import pytest

from dzbench.agent import service as S
from dzbench.session import Session


# ---------------------------------------------------------------- #107 / #109：随机对象的声明直接能起迭代（参数名、量程、容差全从握手 / 声明读）
@pytest.mark.parametrize("seed", list(range(0, 40, 3)) + [101, 202, 3008, 3009, 3010])
def test_randplant_declaration_passes_gen_link(seed, tmp_path):
    """声明层（不起板）：每个随机对象的 app.yaml 都过 gen_link 校验、握手表带 link.step。"""
    import sys as _sys
    _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "tools"))
    import gen_link
    import randplant
    (tmp_path / "app.yaml").write_text(randplant.app_yaml(randplant.gen(seed)), "utf-8")
    spec, params, _ = gen_link.load(tmp_path / "app.yaml")
    assert not gen_link.check(spec, params), gen_link.check(spec, params)
    assert gen_link.schema(spec, params).get("step")


@pytest.mark.needs_sim
@pytest.mark.parametrize("seed", [3, 101, 3008, 3010])
def test_iterate_plan_accepts_any_randplant_declaration(seed, home):
    """真 randplant 对象 → 真 host-sim 仿真板 → 真 Session + AgentService：iterate_plan 走真的 measure_step_timing。
    测出时序就用实测；测不出按默认时长 / 量程 1/4，并在 timing_reason_zh 里写明是回退。"""
    import sys as _sys
    _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "tools"))
    import randplant
    from dzbench import paths
    from dzbench.agent.iterate import Iterator
    from dzbench.agent_api import AgentTools
    p = randplant.gen(seed)
    p["name"] = f"it-plan-{seed}"
    randplant.write(p, paths.projects_dir() / p["name"])
    s = Session()
    s.connect(f"sim:{p['name']}")
    try:
        t0 = time.monotonic()
        while time.monotonic() - t0 < 60 and not (s.schema and len(s.window(0.5)) > 5):
            time.sleep(0.05)
        assert s.schema and s.schema.step, "仿真板起不来 / 没握手"
        svc = S.AgentService(s, AgentTools(s, lambda e: None), lambda e: None)
        st = s.schema.step[0]
        span = st.get("range") if st.get("range") is not None else st.get("sensor_range")
        plan = svc.iterate_plan(_default_target=True)
        o = svc.measure_step_timing()                       # 按端口缓存：就是 iterate_plan 用的那一次
        assert {q["name"] for q in plan["params"]} >= set(p["roles"].values()) - {None}
        assert plan["abs_tol"] == pytest.approx(0.01 * float(span))
        if o.get("step_dur_ms"):
            assert plan["dur_ms"] == int(o["step_dur_ms"])
        else:
            assert plan["dur_ms"] == 2000 and plan["timing_source"] == "fallback" and "默认 2000 ms" in plan["timing_reason_zh"], plan
        if o.get("step_target") is not None:
            assert plan["target"] == pytest.approx(float(o["step_target"]))
        else:
            assert plan["target"] == pytest.approx(round(float(span) / 4, 4)) and "量程 1/4" in plan["timing_reason_zh"], plan
        if plan["timing_source"] == "measured":
            assert plan["timing_reason_zh"] == "阶跃时序按仿真实测"
        vals = {q["name"]: q.get("default", q.get("min", 0.0)) for q in s.schema.params}
        assert Iterator.card(plan, vals, [q["name"] for q in s.schema.params], True)
        if st.get("max_step"):
            with pytest.raises(S.GatewayError) as e:
                svc.iterate_plan(target=float(st["max_step"]) * 1.5)
            assert e.value.code == "step_too_large" and "max_step" in e.value.message
    finally:
        s.disconnect()
