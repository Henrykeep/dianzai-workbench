"""op setpoint_set：只下发目标、不跑阶跃；急停中 / 阶跃中 / hold=timeout 通道一律拒绝且什么都不发；按 link_schema 校验；
成功后清 sp_before_latch。设定值通道 hold（latched | timeout，缺省 timeout）原样透传到 schema 摘要和 status。
真实 app.yaml（fw-runtime 4e24d91 起带 hold）经 gen_link 生成的 schema 也测：car_2wd=timeout、line_car=latched。"""
from __future__ import annotations

import struct
import time

import pytest

from dzbench.schema import Schema
from dzbench.session import LinkError, Session

HOLD_MSG = "这块板子的目标不会保持，重新开始实验即可"


def fixture_schema(hold_a="latched", hold_b=None, step_hold=None):
    fa = {"name": "sp_a", "type": "f32", "unit": "rps", "ref_for": "spd_a"} | ({"hold": hold_a} if hold_a else {})
    fb = {"name": "sp_b", "type": "f32", "unit": "rps", "ref_for": "spd_b"} | ({"hold": hold_b} if hold_b else {})
    step = {"sp": 0, "y": "spd_a", "u_max": 0.9, "range": 10, "abs_tol": 0.05} | ({"hold": step_hold} if step_hold else {})
    return Schema({"version": 1, "hash": 1, "telemetry": {"id": 2, "period_ms": 20, "fields": [
        {"name": "t_ms", "type": "u32"}, fa, {"name": "spd_a", "type": "f32"}, fb, {"name": "spd_b", "type": "f32"}]},
        "params": [{"name": "kp", "type": "f32", "min": 0, "max": 2}], "step": [step]})


@pytest.fixture
def rig(monkeypatch):
    s = Session()
    sent = []
    s.schema = fixture_schema()
    monkeypatch.setattr(s, "send_data", lambda i, p: sent.append((i, p)) or True)
    return s, sent


def test_hold_passthrough_default_timeout():
    sc = fixture_schema(hold_a=None)
    assert [(c["name"], c["slot"], c["hold"]) for c in sc.setpoints()] == [("sp_a", 0, "timeout"), ("sp_b", 1, "timeout")]
    assert fixture_schema(hold_a="latched").setpoints()[0]["hold"] == "latched"
    assert fixture_schema(hold_a=None, step_hold="latched").setpoints()[0]["hold"] == "latched"   # link.step 同槽条目上的 hold
    assert fixture_schema().summary()["setpoints"][0]["hold"] == "latched"
    s = Session()
    s.schema = fixture_schema(hold_b="timeout")
    assert [c["hold"] for c in s.status()["setpoints"]] == ["latched", "timeout"]


def test_setpoint_set_latched_channel_ok(rig):
    s, sent = rig
    s.sp_before_latch = 0.7
    with s.lock:
        s._sp_live = {"sp_a": 0.0, "sp_b": 0.25}
    assert s.setpoint_set("sp_a", 0.4) == {"name": "sp_a", "value": 0.4, "slot": 0}
    assert sent == [(1, struct.pack("<2f", 0.4, 0.25))], "只发一帧 DATA id=1，其他槽位保持当前值"
    assert s.status()["sp_before_latch"] is None


def test_setpoint_set_hold_timeout_rejected_nothing_sent(rig):
    s, sent = rig
    s.schema = fixture_schema(hold_a="latched", hold_b=None)          # sp_b 缺 hold → timeout
    for name in ("sp_b",):
        with pytest.raises(LinkError) as e:
            s.setpoint_set(name, 0.3)
        assert e.value.code == "hold_timeout" and e.value.fix_action == "restart_experiment"
        assert e.value.message == HOLD_MSG and e.value.extra["message_zh"] == HOLD_MSG
    assert sent == []


def test_setpoint_set_validation(rig):
    s, sent = rig
    for name, v, rej in (("kp", 1.0, "name"), ("sp_a", "abc", None), ("sp_a", float("nan"), None), ("sp_a", 11.0, "range")):
        with pytest.raises(LinkError) as e:
            s.setpoint_set(name, v)
        assert e.value.code == "invalid_param"
        if rej:
            assert e.value.extra.get("reject") == rej
    assert sent == []


def test_setpoint_set_rejected_when_locked(rig):
    s, sent = rig
    s.tx_locked = True
    with pytest.raises(LinkError) as e:
        s.setpoint_set("sp_a", 1.0)
    assert e.value.code == "estop_locked" and e.value.fix_action == "estop_clear"
    assert sent == []


def test_setpoint_set_rejected_when_iter_busy(rig):
    s, sent = rig
    s.hb_status = 1 << 17                       # 心跳 bit17：板上阶跃实验进行中
    with pytest.raises(LinkError) as e:
        s.setpoint_set("sp_a", 1.0)
    assert e.value.code == "iter_busy" and e.value.fix_action == "stop_iteration"
    assert e.value.extra["message_zh"] == "阶跃实验进行中，结束或停止后再设定目标"
    assert sent == [], "忙时什么都不发，也不中止本轮"


def _wait(cond, t=20.0):
    t0 = time.monotonic()
    while not cond() and time.monotonic() - t0 < t:
        time.sleep(0.02)
    return cond()


@pytest.mark.needs_sim
def test_car_2wd_without_hold_is_timeout_and_freezes_sp(home, monkeypatch):
    """真 car_2wd 固件还没带 hold → 按 timeout：拒绝且不发；急停前目标照样冻结（sp_before_latch）。"""
    s = Session()
    s.connect("sim:car_2wd")
    try:
        assert _wait(lambda: s.schema is not None and s.samples)
        assert {c["hold"] for c in s.status()["setpoints"]} == {"timeout"}
        sent = []
        real = s.send_data
        monkeypatch.setattr(s, "send_data", lambda i, p: sent.append(i) or real(i, p))
        with pytest.raises(LinkError) as e:
            s.setpoint_set("sp_a", 0.4)
        assert e.value.code == "hold_timeout" and sent == []
        t_end = time.monotonic() + 0.6                   # 持续发目标（cmd_timeout 200 ms），让遥测里有非零设定值
        while time.monotonic() < t_end:
            real(1, struct.pack("<ff", 1.0, 1.0))
            time.sleep(0.05)
        assert _wait(lambda: (s.samples[-1][1]["sp_a"] or 0) > 0.05, 3)
        s.estop()
        s.release_estop_events()
        assert _wait(lambda: s.status()["sp_before_latch"] is not None, 3)
        assert s.status()["sp_before_latch"] > 0.0
        s.cmd("R")
        assert _wait(lambda: not s.tx_locked, 3)
        assert s.status()["sp_before_latch"] > 0.0, "解除后保留，给「恢复急停前目标」"
    finally:
        s.disconnect()


def _real_schema(app: str) -> Schema:
    import pathlib, sys
    root = pathlib.Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "tools"))
    import gen_link as G
    spec, params, _ = G.load(root / "apps" / app / "app.yaml")
    return Schema(G.schema(spec, params))


@pytest.mark.parametrize("app,hold", [("car_2wd", "timeout"), ("line_car", "latched")])
def test_real_app_yaml_hold(app, hold, monkeypatch):
    sc = _real_schema(app)
    sps = sc.setpoints()
    assert sps and {c["hold"] for c in sps} == {hold}
    s = Session(); s.schema = sc; sent = []
    monkeypatch.setattr(s, "send_data", lambda i, p: sent.append((i, p)) or True)
    assert [c["hold"] for c in s.status()["setpoints"]] == [hold] * len(sps)
    name = sps[0]["name"]
    if hold == "timeout":
        with pytest.raises(LinkError) as e:
            s.setpoint_set(name, 0.1)
        assert e.value.code == "hold_timeout" and e.value.fix_action == "restart_experiment" and sent == []
    else:
        assert s.setpoint_set(name, 0.1)["slot"] == 0 and len(sent) == 1
