"""r6 验收 #20 / #25 的回归测试（侧车部分）。"""
from __future__ import annotations

import time
import pathlib

import pytest

from wsui import UI, ServerThread
from dzbench.session import Session


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
        assert e["source"] == "ui" and e["ok"] is True and s.tx_locked
        need, opt = Session.ESTOP_EVENT_KEYS["requested"]
        assert set(e) - {"rid"} == need | opt, set(e)            # 精确等于约定：没有 sent / src / message
        la = ui.wait(lambda e: e.get("type") == "estop" and e.get("state") == "latched", 2, m)
        assert la["source"] == "ui" and la["cause"] == "manual"
        need, opt = Session.ESTOP_EVENT_KEYS["latched"]
        assert need <= set(la) <= need | opt, set(la)            # latency_ms 可选诊断字段
    finally:
        ui.close(); st.stop()


@pytest.mark.needs_sim
def test_estop_not_blocked_by_long_held_session_lock(home):
    """有人长持 session.lock（比如慢的日志/参数读写）时按急停：专用通道不等这把锁，≤200 ms 写出并推事件。"""
    import json
    import threading
    st = ServerThread()
    ui = UI(st.port)
    s = st.srv.session
    try:
        ui.ok("connect", port="sim:car_2wd")
        _wait_status(ui, lambda e: e.get("alive"))
        t1 = time.monotonic()
        while not s.params and time.monotonic() - t1 < 10:   # 参数读完（启动期的读参线程不再抢串口）
            time.sleep(0.05)
        time.sleep(0.3)
        held = threading.Event()

        def hog():
            with s.lock:
                held.set()
                time.sleep(3)
        threading.Thread(target=hog, daemon=True).start()
        held.wait(2)
        hb_t = {}
        orig_hb = s._on_heartbeat

        def spy_hb(payload):
            orig_hb(payload)
            if s.estop_cause and "cause" not in hb_t:
                hb_t["cause"] = time.monotonic()        # 带 estop_cause 的那帧心跳到达并处理完（收线程，持锁期间）
        s._on_heartbeat = spy_hb
        m = ui.mark()
        t0 = time.monotonic()
        ui.ws.send(json.dumps({"op": "estop", "rid": 77, "src": "急停按钮"}))
        rq = ui.wait(lambda e: e.get("type") == "estop" and e.get("state") == "requested", 2, m)
        assert time.monotonic() - t0 <= 0.2
        assert s.tx_locked
        la = ui.wait(lambda e: e.get("type") == "estop" and e.get("state") == "latched", 2, m)
        t_l = time.monotonic()
        # 本地服务这一段（带原因的心跳到达 → WS latched）必须与持锁无关；总时长另含固件心跳周期（固件侧在修，≤500 ms 一拍）
        side = t_l - hb_t["cause"]
        assert side <= 0.05, f"持锁时 心跳到达→latched {side * 1000:.0f} ms"
        # 固件急停上升沿即时心跳 + 侧车先记 requested 再发：实测持锁 3 s 下 p50 3.3 ms / p95 3.9 ms（24 次），收紧到 200 ms
        assert t_l - t0 <= 0.2, f"持锁时 点击→latched {(t_l - t0) * 1000:.0f} ms"
        assert la["seq"] > rq["seq"] and la.get("latency_ms") is not None   # 锁存确认排在 requested 之后
        assert held.is_set() and time.monotonic() - t0 < 2.5    # 整个过程 hog 线程一直持着锁
        assert la["cause"] == "manual" and s.fw_status()["estop_cause"]
    finally:
        ui.close(); st.stop()


def _hb(payload_w=None, cause=None):
    import struct
    p = struct.pack("<IIII", 0x12908C75, 0xABCD, 0, payload_w or 1)
    if cause is not None:
        p += struct.pack("<IIf", cause, 1000, 0.0)
    return p


@pytest.mark.parametrize("how", ["bit10", "estop_cause"])
def test_firmware_estop_latches_sidecar(home, how):
    from dzbench._dzlink import HEARTBEAT, encode
    from dzbench import latch
    s = Session(emit=lambda m: None)
    s.port = "/dev/ttyFAKE0"
    s._bind_schema = lambda h: None
    if how == "bit10":
        s._on_bytes(encode(HEARTBEAT, 0, 1, _hb(1 | (1 << 10))))
        assert s.estop_source == "firmware:estop_flag"
    else:
        s._on_bytes(encode(HEARTBEAT, 0, 1, _hb(1, cause=3)))
        assert s.estop_source == "firmware:stall"
    assert s.tx_locked
    assert latch.get("/dev/ttyFAKE0", None) and latch.get(None, 0xABCD)


def test_agent_tool_tables_have_no_estop_clear_path():
    """Agent 两张工具表（agent_api / loop）里都没有任何解除急停（estop_clear / 'R' / 通用 cmd）的入口。"""
    from dzbench.agent_api import TOOLS as A
    from dzbench.agent.loop import TOOLS as L
    names = [t["name"] for t in A] + [t.get("name") or t["function"]["name"] for t in L]
    bad = [n for n in names if "estop" in n.lower() or "clear" in n.lower() or n in ("R", "cmd", "send_cmd", "send_data", "reset")]
    assert not bad, bad
    import json
    blob = json.dumps(A, ensure_ascii=False) + json.dumps(L, ensure_ascii=False)
    assert "estop_clear" not in blob
    from dzbench.agent.service import AgentService
    assert "R" not in AgentService.START_CMDS


def test_step_start_refuses_when_board_reports_estop():
    from types import SimpleNamespace
    from dzbench.agent.service import AgentService
    from dzbench.session import LinkError
    sent = []
    for s in (SimpleNamespace(tx_locked=False, estop_cause={"cause": "stall"}, hb_status=0, cmd=lambda *a: sent.append(a)),
              SimpleNamespace(tx_locked=False, estop_cause=None, hb_status=1 << 10, cmd=lambda *a: sent.append(a))):
        svc = AgentService.__new__(AgentService)
        svc.s = s
        with pytest.raises(LinkError):
            svc.step_start({"start": [["G"]]})
    assert sent == []


@pytest.mark.needs_sim
def test_estop_clear_sends_only_R_and_notifies(home):
    """解除急停：只发 'R'，不重发运动/设定值、不恢复调参；推 estop cleared + 固定 agent_notice（fix_action=tune_relay），只一次。

    等待方式：先 mark 再发操作（事件可能早于 RPC 回复到达——高负载下 latched 常比 estop 的回复先到，
    旧写法 wait(..., ui.mark()) 在回复之后才取 mark，会把已到的 latched 跳过而超时），超时给足 10 s。"""
    from dzbench._dzlink import DATA
    st = ServerThread()
    ui = UI(st.port)
    s = st.srv.session
    try:
        ui.ok("connect", port="sim:car_2wd")
        _wait_status(ui, lambda e: e.get("alive"))
        time.sleep(0.6)
        m0 = ui.mark()                     # 先取 mark，再发急停
        ui.ok("estop", src="急停按钮")
        ui.wait(lambda e: e.get("type") == "estop" and e.get("state") == "latched", 10, m0)
        sent = []
        orig = s._send

        def spy(kind, id_, payload=b""):
            if kind == DATA:
                sent.append((id_, bytes(payload)))
            return orig(kind, id_, payload)
        s._send = spy
        m = ui.mark()
        ui.ok("cmd", c="R")
        ev = ui.wait(lambda e: e.get("type") == "estop" and e.get("state") == "cleared", 10, m)
        assert {"seq", "t", "source"} <= ev.keys()
        nt = ui.wait(lambda e: e.get("type") == "agent_notice" and e.get("blocker_code") == "estop_cleared", 10, m)
        assert nt["what"] == "已解除，电机保持静止，需重新开始调参" and nt["fix_action"] == "tune_relay"
        time.sleep(1.5)                    # 再看 1.5 s：除 'R' 外没有任何 DATA 帧（主机心跳不是 DATA）
        assert sent == [(0x7E, b"R")], sent
        assert not s.tx_locked
        later = ui.events[m:]
        assert sum(e.get("type") == "agent_notice" and e.get("blocker_code") == "estop_cleared" for e in later) == 1   # 通知只一次
        assert sum(e.get("type") == "estop" and e.get("state") == "cleared" for e in later) == 1
        assert not [e for e in later if str(e.get("type", "")).startswith(("tune", "autopilot"))], "解除后不得恢复调参"
    finally:
        ui.close(); st.stop()


def test_estop_cause_single_source():
    """急停原因只有一个来源 progress.estop_cause_of：fw_status 优先，没上报再读 status.estop_cause；collect 里不再有别的判定。"""
    import inspect
    from dzbench import progress
    a, b = {"cause": "stall", "message_zh": "堵转"}, {"cause": "manual", "message_zh": "手动"}
    assert progress.estop_cause_of({"estop_cause": a}, {"estop_cause": b}) is a
    assert progress.estop_cause_of({"estop_cause": None}, {"estop_cause": b}) is b
    assert progress.estop_cause_of({}, {}) is None
    src = inspect.getsource(progress)
    assert src.count("estop_cause_of(") == 2, "只允许定义一处 + collect 调用一处"
    body = inspect.getsource(progress.collect)
    assert 'st.get("estop_cause")' not in body and 'st["estop_cause"]' not in body
    assert 'fw.get("estop_cause")' not in body


@pytest.mark.parametrize("how", ["requested", "firmware", "flag_then_cause"])
def test_no_separate_estop_cause_event_cause_rides_latched(home, how):
    """不再推 type:"estop_cause"；cause / message_zh 随 estop state:"latched" 下发（人按 / 板子自己 / 急停位先到原因后到）。"""
    from dzbench._dzlink import HEARTBEAT, encode
    out = []
    s = Session(emit=out.append)
    s.port = "/dev/ttyFAKE1"
    s._bind_schema = lambda h: None
    if how == "requested":
        s.estop_source, s.tx_locked, s.estop_requested_at = "ui", True, time.monotonic()
    if how == "flag_then_cause":
        s._on_bytes(encode(HEARTBEAT, 0, 1, _hb(1 | (1 << 10))))
    s._on_bytes(encode(HEARTBEAT, 0, 2, _hb(1 | (1 << 10), cause=3)))
    assert not [m for m in out if m.get("type") == "estop_cause"]
    la = [m for m in out if m.get("type") == "estop" and m.get("state") == "latched" and m.get("cause")]
    assert la and la[-1]["cause"] == "stall" and la[-1]["message_zh"], out
    assert la[-1]["source"] == ("ui" if how == "requested" else "firmware:stall")
    assert {"seq", "t"} <= la[-1].keys()


def test_estop_event_keys_match_contract():
    s = Session()
    for st, kw in (("requested", {"ok": True, "message_zh": "x"}),
                   ("latched", {"cause": "manual", "message_zh": "x", "latency_ms": 12}),
                   ("latched", {}), ("cleared", {"message_zh": "x"})):
        need, opt = Session.ESTOP_EVENT_KEYS[st]
        e = s.estop_ev(st, "ui", **kw)
        assert need <= set(e) <= need | opt and set(e) == need | set(kw), (st, set(e))
    doc = (pathlib.Path(__file__).resolve().parents[3] / "docs/dev/events.md").read_text(encoding="utf-8")
    for st, (need, opt) in Session.ESTOP_EVENT_KEYS.items():
        for k in need | opt:
            assert f"`{k}`" in doc, (st, k)                       # 约定文档与代码一致
