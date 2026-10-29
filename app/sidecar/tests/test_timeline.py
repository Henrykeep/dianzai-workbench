"""事件时间线：分类表 + 会话内事件（心跳丢失 / CRC 突增）+ 带 dzlog 时间。"""
import time

import pytest

from dzbench import events
from dzbench.events import Timeline, crc_spike


def test_classify_table():
    assert events.from_broadcast({"type": "param", "name": "kp", "value": 0.3, "status": "ok"}) == ("param", "kp = 0.3")
    assert events.from_broadcast({"type": "param", "name": "kp", "value": 2, "status": "clamped"})[1].endswith("（clamped）")
    assert events.from_broadcast({"type": "estop", "sent": False}) == ("estop", "急停（未送达）")
    assert events.from_broadcast({"type": "tune_round", "verdict": {"action": "keep"}, "metrics": {"overshoot_pct": 12.34}})[1] == "阶跃实验完成 · 超调 12.3% · keep"
    assert events.from_broadcast({"type": "change", "status": "applied", "id": 3, "title": "改 kp"}) == ("agent", "采纳改动 #3 改 kp")
    assert events.from_broadcast({"type": "change", "status": "pending", "id": 3}) is None
    assert events.from_broadcast({"type": "event", "kind": "param"}) is None          # 自己发的不再归类
    assert events.from_reply("connect", {"port": "sim:car_2wd", "baud": 0}) == ("connect", "连接 sim:car_2wd")
    assert events.from_reply("proposal_decide", {"status": "applied", "name": "kp", "applied": 0.2}) == ("agent", "采纳提议 kp = 0.2")
    assert events.from_reply("proposal_decide", {"status": "rejected"}) is None
    assert events.from_reply("list_ports", []) is None


def test_crc_spike_and_timeline():
    assert not crc_spike({"crc": 2}, [])
    assert crc_spike({"crc": 3}, [])
    assert not crc_spike({"crc": 6}, [{"crc": 4}] * 30)                              # 一直有干扰：不刷屏
    assert crc_spike({"crc": 12}, [{"crc": 4}] * 30)
    tl = Timeline(keep=2)
    for k in range(3):
        tl.add("param", str(k), 1.0 * k, None)
    h = tl.history()
    assert [e["i"] for e in h] == [1, 2] and h[1]["log_t"] == 2.0


@pytest.mark.needs_sim
def test_sim_events(home):
    from dzbench.session import Session
    got = []
    s = Session(emit=got.append)
    s.connect("sim:car_2wd")
    try:
        t0 = time.monotonic()
        while time.monotonic() - t0 < 5 and not (s.schema and len(s.params) == 5):
            s.status(); time.sleep(0.05)
        s.set_param("kp", 0.3)
        e = s.mark(*events.from_broadcast({"type": "param", "name": "kp", "value": 0.3}))
        assert e["log_t"] is not None and e["log_t"] > 0 and e["plot_t"] is not None
        assert any(m.get("type") == "event" for m in got)
        s.tr.close()                                   # 模拟板子不再发：心跳超时 → watchdog 事件
        s.tr = type("Dead", (), {"close": lambda self: None, "write": lambda self, b: None})()
        t0 = time.monotonic()
        while time.monotonic() - t0 < 4 and not any(x["kind"] == "watchdog" for x in s.timeline.history()):
            s.status(); time.sleep(0.1)
        assert any(x["kind"] == "watchdog" for x in s.timeline.history())
    finally:
        s.tr = None
        s.disconnect()
