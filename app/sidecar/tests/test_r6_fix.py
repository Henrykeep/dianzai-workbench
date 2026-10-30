"""r6 验收 #20 / #25 的回归测试（侧车部分）。"""
from __future__ import annotations

import time

import pytest

from wsui import UI, ServerThread


def _locked(ui):
    return ui.wait(lambda e: e.get("type") == "status" and e.get("connected"), 5, ui.mark())["tx_locked"]


def _wait_status(ui, pred, t=8.0):
    return ui.wait(lambda e: e.get("type") == "status" and pred(e), t, ui.mark())


# ---------------------------------------------------------------- #20 急停锁存跨重连 / 侧车重启
@pytest.mark.needs_sim
def test_estop_latch_survives_reconnect_and_restart(home):
    st = ServerThread()
    ui = UI(st.port)
    try:
        ui.ok("connect", port="sim:car_2wd")
        _wait_status(ui, lambda e: e.get("alive"))
        ui.ok("estop", src="急停按钮")
        assert _locked(ui) is True
        ui.ok("disconnect")
        ui.ok("connect", port="sim:car_2wd")
        s = _wait_status(ui, lambda e: e.get("alive"))
        assert s["tx_locked"] is True, "重连不能解除急停锁存"
        assert ui.call("param_set", name="kp", value=0.1)["ok"] is not None
        bl = {b["code"]: b for b in ui.ok("progress.get")["blockers"]}
        assert "estop" in bl and bl["estop"]["fix_action"] == "estop_clear" and bl["estop"]["source"] == "ui"
    finally:
        ui.close(); st.stop()
    time.sleep(0.3)
    st2 = ServerThread()                                  # 侧车重启：同一个 DZBENCH_HOME
    ui2 = UI(st2.port)
    try:
        ui2.ok("connect", port="sim:car_2wd")
        s = _wait_status(ui2, lambda e: e.get("alive"))
        assert s["tx_locked"] is True, "侧车重启后急停锁存要保持"
        assert "estop" in {b["code"] for b in ui2.ok("progress.get")["blockers"]}
        ui2.ok("cmd", c="R")                              # 只有人点“解除急停 R”才解
        s = _wait_status(ui2, lambda e: not e.get("tx_locked"))
        assert s["tx_locked"] is False
        ui2.ok("disconnect"); ui2.ok("connect", port="sim:car_2wd")
        assert _wait_status(ui2, lambda e: e.get("alive"))["tx_locked"] is False
    finally:
        ui2.close(); st2.stop()


def test_latch_store_keys(home):
    from dzbench import latch
    latch.set("sim:car_2wd+hw", 0x1234, "ui")
    assert latch.get("sim:car_2wd", None)["source"] == "ui"
    assert latch.get("/dev/ttyUSB9", 0x1234)["source"] == "ui"     # 换了口也按芯片 ID 认出来
    latch.clear("sim:car_2wd", 0x1234)
    assert latch.get("sim:car_2wd", 0x1234) is None
    assert latch.get("replay:/x.dzlog", None) is None


def test_agent_cannot_send_estop_clear():
    from dzbench.agent_api import TOOLS
    assert not any("estop_clear" in t["name"] or t["name"] in ("cmd", "send_cmd") for t in TOOLS)


# ---------------------------------------------------------------- #25 Agent 长调用不阻塞心跳 / 回执
@pytest.mark.needs_sim
def test_slow_agent_does_not_block_heartbeat_and_acks_each_message(home):
    st = ServerThread()
    ui = UI(st.port)
    calls = []

    def slow_ask(text):
        calls.append(text)
        time.sleep(10 if len(calls) == 1 else 0.2)
        return "好的：" + text
    st.srv.svc.ask = slow_ask
    try:
        ui.ok("connect", port="sim:car_2wd")
        _wait_status(ui, lambda e: e.get("alive"))
        m0 = ui.mark()
        rids = []
        import itertools  # noqa: F401
        for i in range(3):
            rid = next(ui.rid); rids.append(rid)
            ui.ws.send(__import__("json").dumps({"op": "agent_ask", "rid": rid, "msg_id": f"u{i}", "text": f"第{i + 1}条"}))
        acks = [ui.wait(lambda e, i=i: e.get("type") == "agent_ack" and e.get("msg_id") == f"u{i}", 1.0, m0) for i in range(3)]
        assert acks[0]["state"] == "running" and [a["state"] for a in acks[1:]] == ["queued", "queued"]
        t0 = time.monotonic()
        alive_seen = 0
        while time.monotonic() - t0 < 10.5:               # 10 s 慢调用期间：心跳不断、不急停、其他操作照常回复
            s = _wait_status(ui, lambda e: True, 2)
            assert s["alive"] and not s["tx_locked"] and not s.get("estop_cause"), s
            alive_seen += 1
            r = ui.call("param_read_all", timeout=2)
            assert r["ok"]
        assert alive_seen >= 10
        assert not [e for e in ui.events[m0:] if e.get("type") == "event" and e.get("kind") in ("estop", "watchdog")]
        with ui.cv:
            assert ui.cv.wait_for(lambda: all(r in ui.replies for r in rids), 10)
        assert [ui.replies[r]["data"] for r in rids] == ["好的：第1条", "好的：第2条", "好的：第3条"]
    finally:
        ui.close(); st.stop()


@pytest.mark.needs_sim
def test_estop_blocks_agent_message_and_notice(home):
    st = ServerThread()
    ui = UI(st.port)
    st.srv.svc.ask = lambda text: "不该被调用"
    try:
        ui.ok("connect", port="sim:car_2wd")
        _wait_status(ui, lambda e: e.get("alive"))
        time.sleep(0.6)
        m0 = ui.mark()
        t0 = time.monotonic()
        ui.ok("estop", src="急停按钮")
        n = ui.wait(lambda e: e.get("type") == "agent_notice" and e.get("blocker_code") == "estop", 1.0, m0)
        assert time.monotonic() - t0 < 1.0
        assert n["source"] == "ui" and n["fix_action"] == "estop_clear" and n["human_only"] is True and n["suggestion"]
        ev = [e for e in ui.events[m0:] if e.get("type") == "event" and e.get("kind") in ("estop", "watchdog")]
        assert ev and all(e.get("source") for e in ev), ev
        r = ui.call("agent_ask", text="继续调参", msg_id="b1")
        assert r["ok"] is False and r["error"]["code"] == "estop_locked" and r["error"]["fix_action"] == "estop_clear"
        a = ui.wait(lambda e: e.get("type") == "agent_ack" and e.get("msg_id") == "b1", 1, m0)
        assert a["state"] == "blocked" and a["reason"] == "estop" and a["message"].startswith("已急停，请先解除")
        assert a["fix_action"] == "estop_clear" and a["text"] == "继续调参"
        time.sleep(1.0)                                    # 再推几次 progress.changed 也不重复提醒
        assert len([e for e in ui.events[m0:] if e.get("type") == "agent_notice" and e.get("blocker_code") == "estop"]) == 1
    finally:
        ui.close(); st.stop()


def test_notifier_dedup_and_fields():
    from dzbench.notices import Notifier
    nt = Notifier()
    snap = {"blockers": [{"code": "estop", "message": "急停已锁存：x", "fix_action": "estop_clear", "source": "heartbeat_lost"}]}
    a = nt.update(snap)
    assert len(a) == 1 and a[0]["source"] == "heartbeat_lost" and a[0]["human_only"] and a[0]["fix_action"] == "estop_clear"
    assert nt.update(snap) == []
    assert nt.update({"blockers": []}) == []
    assert len(nt.update(snap)) == 1                      # 清除后再出现才再提醒
    b = Notifier().update({"blockers": [{"code": "params_not_saved", "message": "m", "fix_action": "params_flash"}]})
    assert b[0]["human_only"] is False and b[0]["source"] == "progress"


def test_estop_sources_never_unknown():
    from dzbench.session import estop_source, hb_status_event
    from dzbench.events import Timeline, from_broadcast
    assert estop_source("急停按钮") == "ui" and estop_source("agent") == "agent"
    assert from_broadcast({"type": "estop", "sent": True, "src": "Esc"})[2] == "ui"
    m = hb_status_event(4)
    assert m and m[2].startswith("firmware:")
    e = Timeline().add("watchdog", "x", None, None, "heartbeat_lost")
    assert e["source"] == "heartbeat_lost" and e["detail"] == "x"


# ---------------------------------------------------------------- #25 急停延迟（安全 P0）
@pytest.mark.needs_sim
@pytest.mark.parametrize("busy", ["idle", "slow_llm", "slow_op"])
def test_estop_latency_under_200ms(home, busy):
    import json
    st = ServerThread()
    ui = UI(st.port)
    s = st.srv.session
    st.srv.svc.ask = lambda text: (time.sleep(10), "x")[1]
    st.srv.svc.run_sweep_test = lambda: (time.sleep(10), {})[1]
    try:
        ui.ok("connect", port="sim:car_2wd")
        _wait_status(ui, lambda e: e.get("alive"))
        time.sleep(0.6)
        if busy == "slow_llm":
            ui.ws.send(json.dumps({"op": "agent_ask", "rid": 900, "text": "慢"}))
        elif busy == "slow_op":                          # 同一连接上一个 10 s 的长操作还没回复
            ui.ws.send(json.dumps({"op": "tune_sweep_test", "rid": 901}))
        time.sleep(0.5)
        m = ui.mark()
        t0 = time.monotonic()
        ui.ws.send(json.dumps({"op": "estop", "rid": 902, "src": "急停按钮"}))
        e = ui.wait(lambda e: e.get("type") == "estop" and e.get("state") == "requested", 2, m)
        dt = time.monotonic() - t0
        assert dt <= 0.2, f"急停事件 {dt * 1000:.0f} ms"
        assert e["source"] == "ui" and e["sent"] is True and s.tx_locked
        la = ui.wait(lambda e: e.get("type") == "estop" and e.get("state") == "latched", 2, m)
        assert la["source"] == "ui" and la["cause"] == "manual"
    finally:
        ui.close(); st.stop()
