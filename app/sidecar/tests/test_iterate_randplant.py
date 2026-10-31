"""#107：任意 randplant 随机对象（随机参数名 / 只声明 sensor_range、max_step）上 iterate_start 真的进入迭代，
仿真里至少跑完一轮（iterate.round 事件），不出 KeyError / “没有这些参数”。"""
from __future__ import annotations

import pathlib
import shutil
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))

pytestmark = pytest.mark.needs_sim

SEEDS = [1, 7, 13, 21, 101, 202, 3008, 5003]


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
        names = set(p["roles"].values())
        assert names <= {q["name"] for q in svc.iterate_plan(target=tgt)["params"]}
    finally:
        s.disconnect()
        shutil.rmtree(ROOT / "build/host-sim" / p["name"], ignore_errors=True)
