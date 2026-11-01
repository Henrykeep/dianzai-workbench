"""#107：任意 randplant 随机对象（随机参数名 / 只声明 sensor_range、max_step）上 iterate_start 真的进入迭代，
仿真里至少跑完一轮（iterate.round 事件），不出 KeyError / “没有这些参数”。"""
from __future__ import annotations

import pathlib
import shutil
import sys
import time

import pytest

from dzbench.agent import service as S

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))

pytestmark = pytest.mark.needs_sim

SEEDS = [1, 7, 13, 21, 101, 202, 3008, 5003]
MEASURED: list[int] = []


@pytest.mark.timeout(240)   # 合法地长：慢对象（如种子 21）no_rise 时阶跃时长逐轮翻倍到 30 s，迭代本身预算 BUDGET_S=180 s，测试 join(180)
@pytest.mark.parametrize("seed", SEEDS)
def test_iterate_start_runs_rounds_on_randplant(seed, home, tmp_path, monkeypatch):
    import randplant
    from dzbench import paths
    from dzbench.agent.service import AgentService
    from dzbench.agent_api import AgentTools
    from dzbench.session import Session
    p = randplant.gen(seed)
    p["name"] = f"itr-{p['name']}"
    shutil.rmtree(ROOT / "build/host-sim" / p["name"], ignore_errors=True)
    randplant.write(p, paths.projects_dir() / p["name"])
    monkeypatch.setattr(AgentService, "ITER_ROUNDS", 1)
    s, ev = Session(), []
    s.connect("sim:" + p["name"])
    try:
        t0 = time.monotonic()
        while not (s.schema and len(s.params) == len(s.schema.params)) and time.monotonic() - t0 < 60:
            time.sleep(0.05)
        svc = AgentService(s, AgentTools(s, ev.append), ev.append, root=tmp_path)
        st = s.schema.step[0]
        tgt = min(0.25 * st["sensor_range"], st.get("max_step") or 1e9)
        r = svc.iterate_start(target=tgt, dur_ms=1500)
        assert r.get("status") == "started", r
        svc.iter_thread.join(180)
        rounds = [e for e in ev if e.get("type") == "iterate.round"]
        assert rounds, [e.get("type") for e in ev][-10:]
        assert svc.iter_result and svc.iter_result.get("reason") != "error", svc.iter_result
        plan = svc.iterate_plan(target=tgt, dur_ms=1500)
        assert {n for r, n in p["roles"].items() if r not in ("LIM", "other")} == {q["name"] for q in plan["params"]}   # 参数名全从握手读，LIM 不调
        assert plan["abs_tol"] == pytest.approx(0.01 * st["sensor_range"])           # 没写 abs_tol：量程的 1%
        assert "fallback" not in plan
        # 不给 dur_ms：真会话上实测阶跃时序（不退默认）
        auto = svc.iterate_plan(dur_ms=None, _default_target=True)
        if "fallback" in auto:                      # 实测没辨识出来（如很慢的对象）：必须写明退了什么、为什么
            assert auto["fix_action"] == "measure_step_timing" and "探测" in auto["message_zh"], auto
        else:
            MEASURED.append(seed)
        assert 200 <= auto["dur_ms"] <= 30000, auto
        assert abs(auto["target"]) <= (st.get("max_step") or 1e9) + 1e-9
        # #109：超过 max_step 拒绝，带 message_zh / fix_action
        if st.get("max_step"):
            with pytest.raises(S.GatewayError) as e:
                svc.iterate_plan(target=float(st["max_step"]) * 1.5, dur_ms=1500)
            assert e.value.code == "step_too_large" and e.value.fix_action == "lower_step"
        # 实测失败：退到量程 1/4（再夹 max_step），并写明退了什么
        def boom():
            raise RuntimeError("测不出")
        monkeypatch.setattr(svc, "measure_step_timing", boom)
        fb = svc.iterate_plan(dur_ms=None, _default_target=True)
        assert "span_quarter" in fb["fallback"] and "dur_default" in fb["fallback"] and fb["fix_action"] == "measure_step_timing"
        assert "测不出" in fb["message_zh"] and "1/4" in fb["message_zh"]
        assert fb["target"] == pytest.approx(min(st["sensor_range"] / 4, st.get("max_step") or 1e9))
    finally:
        s.disconnect()
        shutil.rmtree(ROOT / "build/host-sim" / p["name"], ignore_errors=True)


def test_real_measurement_used_on_most_seeds():
    """上面跑过的种子里，大多数真用了实测时序（不是全靠退默认）。"""
    if not MEASURED:
        pytest.skip("单独运行时没有前面的参数化结果")
    assert len(MEASURED) >= len(SEEDS) // 2, MEASURED
