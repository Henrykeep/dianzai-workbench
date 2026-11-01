"""侧车被杀后重启：自动连回上次的板子（3 s 内 link.state=connected）；用户点过“断开”就不再自动连；
口没了 → board=disconnected、reason=port_not_found。pty 仿真板 + 真侧车进程（SIGKILL 重启）。"""
import json
import os
import signal
import subprocess
import sys
import time

import pytest

SIDECAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _start(home):
    from wsui import free_port, wait_port
    port = free_port()
    env = dict(os.environ, PYTHONPATH=SIDECAR, DZBENCH_HOME=str(home))
    p = subprocess.Popen([sys.executable, "-m", "dzbench", "--port", str(port)], env=env, cwd=SIDECAR,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_port(port)
    return p, port


def _kill(p):
    p.send_signal(signal.SIGKILL)
    p.wait()


def _link(ui):
    return ui.ok("hello")["link"] or {}


def _until(f, t):
    end = time.monotonic() + t
    while time.monotonic() < end:
        v = f()
        if v:
            return v
        time.sleep(0.05)
    return f()


@pytest.fixture
def board(home, tmp_path):
    from ptyboard import PtyBoard
    b = PtyBoard("car_2wd", tmp_path / "ttyDZ0")
    yield b
    b.close()


@pytest.mark.needs_sim
def test_restart_auto_reconnects_within_3s(board, home):
    from wsui import UI
    p, port = _start(home)
    try:
        ui = UI(port)
        ui.ok("connect", port=str(board.path), baud="auto")
        ui.wait(lambda e: e["type"] == "schema")
        assert _until(lambda: (json.loads((home / "last_session.json").read_text()).get("schema_hash")), 3), \
            "收到心跳后要记下板子身份"
        ui.close()
        _kill(p)
        t0 = time.monotonic()
        p, port = _start(home)
        ui = UI(port)
        assert _until(lambda: _link(ui).get("board") == "connected", 3.0 - (time.monotonic() - t0) + 0.5), \
            "侧车重启后 3 s 内自动连回"
        assert time.monotonic() - t0 < 3.5
        assert ui.ok("hello")["status"]["port"] == str(board.path)
        ui.close()
    finally:
        p.kill()


@pytest.mark.needs_sim
def test_explicit_disconnect_disables_auto_reconnect(board, home):
    from wsui import UI
    p, port = _start(home)
    try:
        ui = UI(port)
        ui.ok("connect", port=str(board.path), baud="auto")
        ui.wait(lambda e: e["type"] == "schema")
        ui.ok("disconnect")
        assert not (home / "last_session.json").exists()
        ui.close()
        _kill(p)
        p, port = _start(home)
        ui = UI(port)
        time.sleep(3.0)
        h = ui.ok("hello")
        assert h["recovered"] is None
        assert not h["status"]["connected"] and (h["link"] or {}).get("board", "disconnected") == "disconnected"
        ui.close()
    finally:
        p.kill()


def test_port_gone_reports_port_not_found(home, monkeypatch):
    """原口不在了、也重扫不到同一块板：disconnected + reason=port_not_found，记录留着（下次重启再试）。"""
    from dzbench import lastsession, ports, session as session_mod
    monkeypatch.setattr(session_mod.Session, "RESUME_TRIES", (0.0, 0.01))
    lastsession.mark("/dev/ttyDZ_gone", 115200, ("1a86", "7523", None))
    rec = lastsession.take_unclean()
    seen = []
    s = session_mod.Session(emit=seen.append)
    def boom(port, baud):
        raise OSError("no such port")
    s._open = boom
    monkeypatch.setattr(ports, "pick_moved", lambda *a, **k: (None, "none"))
    r = s.resume(rec)
    assert r == {"resumed": False, "reason": "port_not_found"}
    ev = s.link_state(now=time.monotonic())
    assert ev["board"] == "disconnected" and ev["reason"] == "port_not_found" and ev["port"] is None
    assert any(e.get("code") == "port_not_found" for e in seen)
    assert lastsession.read()["port"] == "/dev/ttyDZ_gone"
    s.disconnect()                                    # 用户点“断开”：原因清掉、记录删掉
    assert lastsession.read() is None
    assert s.link_state(now=time.monotonic() + 5)["reason"] is None


def test_rescan_follows_board_to_new_port(home, monkeypatch):
    from dzbench import lastsession, ports, session as session_mod
    monkeypatch.setattr(session_mod.Session, "RESUME_TRIES", (0.0,))
    lastsession.mark("/dev/ttyOLD", 115200, ("1a86", "7523", "S1"))
    lastsession.mark_board("/dev/ttyOLD", 0x1234, 0xABCD)
    rec = lastsession.take_unclean()
    assert rec["board_uid"] == 0x1234
    got = {}
    monkeypatch.setattr(ports, "pick_moved", lambda port, ident, uid, sh, baud: got.update(a=(port, ident, uid, sh)) or ("/dev/ttyNEW", "uid"))
    class Tr:
        def start(self, *a): pass
        def close(self): pass
    def opener(port, baud):
        if port == "/dev/ttyOLD":
            raise OSError("gone")
        return Tr()
    s = session_mod.Session()
    s._open = opener
    r = s.resume(rec)
    assert r["resumed"] and r["port"] == "/dev/ttyNEW"
    assert got["a"] == ("/dev/ttyOLD", ("1a86", "7523", "S1"), 0x1234, 0xABCD)
    s.disconnect()


def test_resume_bind_timeout_is_declared_setting(monkeypatch):
    """#160：5 s 是声明式设置 link.resume_bind_timeout_s，环境变量可覆盖；原因码在总表里带 message_zh + fix_action。"""
    from dzbench import config
    from dzbench.agent import reason_codes
    from dzbench.session import Session
    assert config.DEFAULTS["link"]["resume_bind_timeout_s"] == 5.0
    monkeypatch.delenv("DZBENCH_RESUME_BIND_TIMEOUT_S", raising=False)
    assert Session.resume_bind_timeout_s() == 5.0
    monkeypatch.setenv("DZBENCH_RESUME_BIND_TIMEOUT_S", "1.5")
    assert Session.resume_bind_timeout_s() == 1.5
    row = reason_codes.table()["resume_no_response"]
    assert row["message_zh"] == "重连后板子没有回应，请按『重新连接』" and row["fix_action"] == "reconnect" and row["kind"] == "blocker"


def test_reconnect_op_reopens_last_port(monkeypatch):
    """#160：fix_action=reconnect → WS op "reconnect"（Session.reconnect）：重开当前/上次的口；从没连过 → no_port。"""
    from dzbench import lastsession
    from dzbench.session import LinkError, Session
    s = Session()
    calls = []
    monkeypatch.setattr(s, "connect", lambda port, baud=None, log=True: calls.append((port, baud)) or {"port": port})
    monkeypatch.setattr(lastsession, "read", lambda: {"port": "/dev/ttyUSB7", "baud": 460800})
    assert s.reconnect() == {"port": "/dev/ttyUSB7"} and calls == [("/dev/ttyUSB7", 460800)]
    monkeypatch.setattr(lastsession, "read", lambda: None)
    with pytest.raises(LinkError) as e:
        s.reconnect()
    assert e.value.code == "no_port"
