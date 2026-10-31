"""op setpoint_set：只下发目标、不跑阶跃；急停中拒绝（estop_locked + fix_action）；按 link_schema 校验；成功后清 sp_before_latch。"""
from __future__ import annotations

import time

import pytest

from dzbench.session import LinkError, Session


def _wait(cond, t=20.0):
    t0 = time.monotonic()
    while not cond() and time.monotonic() - t0 < t:
        time.sleep(0.02)
    return cond()


def _last(s, k):
    with s.lock:
        return s.samples[-1][1][k] if s.samples else None


@pytest.mark.needs_sim
def test_setpoint_set_car_2wd(home):
    s = Session()
    s.connect("sim:car_2wd")
    try:
        assert _wait(lambda: s.schema is not None and s.samples)
        assert s.setpoint_names()[:2] == ["sp_a", "sp_b"]
        # 校验：不是设定值 / 非数 / 超 link.step.range → invalid_param，不钳位
        for name, v, rej in (("kp", 1.0, "name"), ("sp_a", "abc", None), ("sp_a", float("nan"), None), ("sp_a", 11.0, "range")):
            with pytest.raises(LinkError) as e:
                s.setpoint_set(name, v)
            assert e.value.code == "invalid_param"
            if rej:
                assert e.value.extra.get("reject") == rej
        r = s.setpoint_set("sp_a", 0.4)
        assert r == {"name": "sp_a", "value": 0.4, "slot": 0}
        assert _wait(lambda: (_last(s, "sp_a") or 0) > 0.05, 3), "目标已下发（car_2wd 设定值有斜坡 + 200 ms cmd_timeout）"
        assert not s.iter_busy() and not s.step_results, "只写目标，不跑阶跃"
        # 急停：冻结急停前目标；锁存中拒绝
        s.estop()
        s.release_estop_events()
        assert _wait(lambda: s.status()["sp_before_latch"] is not None, 3)
        assert s.status()["sp_before_latch"] > 0.0
        with pytest.raises(LinkError) as e:
            s.setpoint_set("sp_a", 0.2)
        assert e.value.code == "estop_locked" and e.value.fix_action == "estop_clear"
        s.cmd("R")
        assert _wait(lambda: not s.tx_locked, 3)
        assert s.status()["sp_before_latch"] > 0.0, "解除后保留，给「恢复急停前目标」"
        s.setpoint_set("sp_a", 0.4)
        assert s.status()["sp_before_latch"] is None
    finally:
        s.disconnect()


def test_setpoint_set_rejected_when_locked():
    s = Session()
    s.tx_locked = True
    with pytest.raises(LinkError) as e:
        s.setpoint_set("sp_a", 1.0)
    assert e.value.code == "estop_locked" and e.value.fix_action == "estop_clear"


def test_setpoint_set_rejected_when_iter_busy(monkeypatch):
    s = Session()
    sent = []
    monkeypatch.setattr(s, "send_data", lambda *a: sent.append(a) or True)
    s.hb_status = 1 << 17                       # 心跳 bit17：板上阶跃实验进行中
    with pytest.raises(LinkError) as e:
        s.setpoint_set("sp_a", 1.0)
    assert e.value.code == "iter_busy" and e.value.fix_action == "stop_iteration"
    assert e.value.extra["message_zh"] == "阶跃实验进行中，结束或停止后再设定目标"
    assert sent == [], "忙时什么都不发，也不中止本轮"
