"""参数写板：回读比对、提议过期作废、一张卡只能落地一次。仿真板。"""
import time

import pytest

from dzbench.agent_api import AgentTools
from dzbench.session import LinkError
from dzbench.session import Session

pytestmark = pytest.mark.needs_sim


@pytest.fixture
def s(home):
    s = Session()
    s.connect("sim:car_2wd")
    t0 = time.monotonic()
    while not (s.schema and len(s.params) == len(s.schema.params)) and time.monotonic() - t0 < 10:
        time.sleep(0.05)
    yield s
    s.disconnect()


def test_readback_ok_and_mismatch(s):
    name = s.schema.params[0]["name"]
    v = s.params[name] * 0.9 or 0.01
    r = s.set_param(name, v, verify=True)
    assert abs(r["readback"] - r["applied"]) < 1e-6
    s.read_param = lambda n: r["applied"] + 1.0
    with pytest.raises(LinkError) as e:
        s.set_param(name, v, verify=True)
    assert e.value.code == "readback_mismatch"


def test_stale_and_single_shot(s):
    name = s.schema.params[0]["name"]
    t = AgentTools(s, lambda e: None)
    pid = t.propose_param_change(name, s.params[name] * 0.8 or 0.02, "t")["id"]
    s.set_param(name, s.params[name] * 1.1 + 0.001)        # 用户在卡片待确认期间拖了滑条
    t0 = time.monotonic()
    while time.monotonic() - t0 < 2 and abs(s.params[name] - t.pending[pid]["current"]) < 1e-9:
        time.sleep(0.02)
    with pytest.raises(LinkError) as e:
        t.decide(pid, True)
    assert e.value.code == "stale_proposal"
    pid = t.propose_param_change(name, s.params[name] * 0.8 or 0.02, "t")["id"]
    assert "readback" in t.decide(pid, True)
    with pytest.raises(LinkError):
        t.decide(pid, True)


def test_tuned_params_revert_unless_kept(s, tmp_path):
    from dzbench.agent.service import AgentService
    ev = []
    t = AgentTools(s, ev.append)
    svc = AgentService(s, t, ev.append, root=tmp_path)
    name = s.schema.params[0]["name"]
    old = s.params[name]
    svc.agent_propose_param(name, old * 0.9 or 0.01, "t")
    pid = next(e["id"] for e in ev if e.get("type") == "proposal")
    t.decide(pid, True)
    st = svc.tune_status()
    assert st["pending"] and st["items"][0]["orig"] == old
    r = svc.tune_finish(False)
    assert abs(r["restored"][0]["readback"] - old) < 1e-6 and not svc.tune_status()["pending"]
    assert "没有保留" in svc.loop.messages[-1]["content"]
    with pytest.raises(LinkError):
        svc.tune_finish(True)
