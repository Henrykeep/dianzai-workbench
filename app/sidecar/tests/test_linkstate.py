"""link.state：唯一连接状态源。复现旧逻辑（只看心跳、1.6 s）在丢几个心跳时来回翻转。"""
from dzbench import session as session_mod
from dzbench.linkstate import LOST_AFTER_S, PUSH_EVERY_S, LinkState, board_state


def _feed(ls: LinkState, now: float, last_frame: float, **kw):
    args = dict(port="/dev/ttyUSB0", port_open=True, reconnecting=False, t_connect=0.0)
    args.update(kw)
    return ls.update(now, last_frame=last_frame, **args)


def test_board_states():
    assert board_state(5, False, False, 0, 0) == "disconnected"
    assert board_state(5, True, False, 1, 0) == "connecting"
    assert board_state(5, True, False, 1, 4) == "connected"
    assert board_state(9, True, False, 1, 4) == "lost"
    assert board_state(5, False, True, 1, 4) == "lost"


def test_missed_heartbeats_with_telemetry_do_not_flap():
    """心跳 500 ms，连丢 3 个心跳（CRC/USB 突发），但遥测 20 ms 一帧照常到。
    旧判据 now - last_hb < 1.6 会在 4 Hz 状态里报“不活”；新判据按任一合法帧，始终 connected。"""
    hb = [0.5, 1.0, 1.5, 3.5, 4.0]                    # 2.0 / 2.5 / 3.0 三个心跳丢了
    frames = [i * 0.02 for i in range(1, 250)]       # 遥测到 5 s
    ls, old_alive, boards = LinkState(), [], set()
    for k in range(1, 20):
        now = k * 0.25
        last_hb = max([t for t in hb if t <= now], default=0.0)
        old_alive.append(now - last_hb < 1.6)
        ev = _feed(ls, now, max(t for t in frames if t <= now))
        if ev:
            boards.add(ev["board"])
    assert False in old_alive[6:]                    # 复现：旧逻辑在板子活着时报断开
    assert boards == {"connected"}
    assert ls.last["sidecar"] == "ok" and ls.last["last_rx_ms"] < 100


def test_push_on_change_and_keepalive():
    ls = LinkState()
    e1 = _feed(ls, 0.1, 0.0)
    assert e1["board"] == "connecting" and e1["seq"] == 1 and e1["last_rx_ms"] is None
    assert _feed(ls, 0.2, 0.0) is None                       # 未变化、未到保活间隔：不推
    e2 = _feed(ls, 0.3, 0.25)
    assert e2["board"] == "connected" and e2["since"] >= e1["since"]
    assert _feed(ls, 0.3 + PUSH_EVERY_S, 1.2)["seq"] == 3   # 保活
    e4 = _feed(ls, 1.2 + LOST_AFTER_S + 0.1, 1.2)
    assert e4["board"] == "lost" and e4["reason"] == "no_frames" and e4["last_rx_ms"] > 2000
    e5 = _feed(ls, 5.0, 1.2, port_open=False, reconnecting=True)
    assert e5["board"] == "lost" and e5["reason"] == "transport_closed"
    e6 = _feed(ls, 6.0, 1.2, port_open=False, port="")
    assert e6["board"] == "disconnected" and e6["port"] is None and e6["reason"] is None


def test_session_status_and_link_state_agree(monkeypatch):
    """status.alive 和 link.state 用同一判据（任一合法帧、同一超时），不会一个说断开、一个说已连接。"""
    s = session_mod.Session()
    s.tr, s.port, s._t_tr, s.t_connect = object(), "/dev/ttyUSB0", 0.0, 0.0
    for now, last in ((1.0, 0.99), (2.5, 1.0), (3.5, 1.0)):
        s.last_frame = last
        monkeypatch.setattr(session_mod.time, "monotonic", lambda: now)
        ev = s.link_state(now)
        board = ev["board"] if ev else s.link.last["board"]
        with s.lock:
            alive = (s.tr is not None) and now - s.last_frame <= session_mod.HB_TIMEOUT_S
        assert (board == "connected") == alive, (now, board)
    assert board == "lost"
    s.tr = None
