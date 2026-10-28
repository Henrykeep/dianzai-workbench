"""赛场上会发生的事，按用户的操作走一遍（pty 仿真板 + 真 WebSocket 侧车）：
拔线/插回、换了 USB 口、侧车被杀后重启、两个窗口、连错口、线上乱码。
每一条都要：板子处于安全状态（看板子自己的遥测，不信侧车）+ 用户看到一句中文说明。
Windows 真 COM 口、真 CH340 拔插 【未测】（只在 Linux pty 上验证）。
"""
import os
import random
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt" or not shutil.which("make") or not shutil.which("cc"),
                                reason="pty 仿真板需要 POSIX + make + cc")

SIDECAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GO = struct.pack("<ff", 0.3, 0.0).hex()            # car_2wd 运动命令（id 1）：前进


def han(s: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in s)


def until(f, t=6.0):
    end = time.monotonic() + t
    while time.monotonic() < end:
        v = f()
        if v:
            return v
        time.sleep(0.05)
    return f()


def board_sp(board):
    tl = board.board_telem
    return tl["sp_a"] if tl and time.monotonic() - board.board_t < 0.5 else None


def direct_go(board):
    """绕过侧车直接往板子塞运动命令：验证板子“锁存”了急停（不是只因没有新命令才停）。"""
    from dzbench._dzlink import DATA, encode
    board.proc.stdin.write(encode(DATA, 1, 0, bytes.fromhex(GO)))


@pytest.fixture
def board(home, tmp_path):
    from ptyboard import PtyBoard
    b = PtyBoard("car_2wd", tmp_path / "ttyDZ0")
    yield b
    b.close()


@pytest.fixture
def side():
    from wsui import UI, ServerThread
    st = ServerThread()
    uis = []

    def ui():
        u = UI(st.port)
        uis.append(u)
        return u
    yield st, ui
    for u in uis:
        u.close()
    st.stop()


def drive(ui, board):
    ui.ok("send_data", id=1, hex=GO)
    assert until(lambda: (board_sp(board) or 0) > 0.5), "命令应生效"


def test_unplug_replug(board, side):
    st, mk = side
    ui = mk()
    ui.ok("connect", port=str(board.path), baud="auto")
    ui.wait(lambda e: e["type"] == "schema")
    time.sleep(0.6)
    drive(ui, board)
    m = ui.mark()
    board.unplug()
    e = ui.wait(lambda e: e.get("code") == "link_lost", start=m)
    assert han(e["message"]) and "重连" in e["fix"]
    assert ui.ok("estop")["sent"] is False                       # 线拔了：老实说没发出去
    time.sleep(1.3)
    direct_go(board)
    time.sleep(0.3)
    assert board_sp(board) == 0.0, "拔线 1 s 后板子自己急停并锁存"
    assert han(ui.ok("hello")["status"].get("hint", "")), "重连中要有中文提示"
    board.replug()
    e = ui.wait(lambda e: e["type"] == "reconnected", start=m, timeout=15)
    assert han(e["message"])
    ui.wait(lambda e: e["type"] == "param", start=m, timeout=10)    # 重读了参数
    time.sleep(0.5)
    assert board_sp(board) == 0.0, "插回去不自动解除急停"
    ui.ok("cmd", c="R")
    drive(ui, board)


def test_port_moved(board, side, tmp_path, monkeypatch):
    import dzbench.session as sess
    st, mk = side
    ui = mk()
    ui.ok("connect", port=str(board.path), baud="auto")
    ui.wait(lambda e: e["type"] == "schema")
    new = tmp_path / "ttyDZ1"
    st.srv.session.ident = (0x1A86, 0x7523, "X")
    monkeypatch.setattr(sess, "find_identity", lambda ident: str(new) if ident and new.exists() else None)
    m = ui.mark()
    board.unplug()
    board.path = new
    board.replug()
    e = ui.wait(lambda e: e["type"] == "port_moved", start=m, timeout=15)
    assert e["new"] == str(new) and han(e["message"])
    ui.wait(lambda e: e["type"] == "reconnected", start=m, timeout=10)
    assert st.srv.session.port == str(new)


def test_sidecar_killed_and_restarted(board, home):
    from wsui import UI, free_port, wait_port
    port = free_port()
    env = dict(os.environ, PYTHONPATH=SIDECAR, DZBENCH_HOME=str(home))
    cmd = [sys.executable, "-m", "dzbench", "--port", str(port)]
    p = subprocess.Popen(cmd, env=env, cwd=SIDECAR, stderr=subprocess.PIPE)
    try:
        wait_port(port)
        ui = UI(port)
        ui.ok("connect", port=str(board.path), baud="auto")
        ui.wait(lambda e: e["type"] == "schema")
        time.sleep(0.6)
        drive(ui, board)
        p.send_signal(signal.SIGKILL)                             # 崩溃 / 任务管理器结束
        p.wait()
        ui.close()
        time.sleep(1.4)
        direct_go(board)
        time.sleep(0.3)
        assert board_sp(board) == 0.0, "侧车没了 1 s，板子自己急停并锁存"

        # 第二个侧车抢同一个端口：退出码 3 + 中文说明（外壳据此不再重启）
        p = subprocess.Popen(cmd, env=env, cwd=SIDECAR)
        wait_port(port)
        p2 = subprocess.run(cmd, env=env, cwd=SIDECAR, capture_output=True, text=True, timeout=20)
        assert p2.returncode == 3 and "已被占用" in p2.stderr

        ui = UI(port)                                             # 外壳把侧车重启后，界面自动重连
        h = ui.ok("hello")
        assert h["recovered"]["port"] == str(board.path) and "意外退出" in h["recovered"]["message"]
        assert not h["status"]["connected"], "重启后不自动连板子"
        ui.ok("connect", port=str(board.path), baud="auto")
        ui.wait(lambda e: e["type"] == "schema")
        time.sleep(0.5)
        assert board_sp(board) == 0.0
        ui.ok("cmd", c="R")
        drive(ui, board)
        ui.ok("disconnect")
        ui.close()
        p.send_signal(signal.SIGTERM)                             # 正常关掉：下次不报“意外退出”
        p.wait(10)
        assert not (home / "last_session.json").exists()
    finally:
        p.kill()


def test_two_windows(board, side):
    st, mk = side
    a, b = mk(), mk()
    a.ok("connect", port=str(board.path), baud="auto")
    a.wait(lambda e: e["type"] == "schema")
    assert until(lambda: b.ok("hello")["status"]["clients"] == 2)
    m = b.mark()
    a.ok("param_set", name="max_rps", value=4.0)
    b.wait(lambda e: e["type"] == "param" and e["name"] == "max_rps" and abs(e["value"] - 4.0) < 1e-6, start=m)
    a.ok("estop")
    b.wait(lambda e: e["type"] == "tx_locked" and e["on"], start=m)   # 一个窗口急停，另一个也看到锁定


def test_port_exclusive(board, home):
    """另一个程序（串口助手 / 第二个侧车）已经占着这个口：第二个打开直接中文报“被占着”。"""
    from dzbench.session import LinkError, Session
    s1, s2 = Session(), Session()
    try:
        s1.connect(str(board.path), 115200)
        with pytest.raises(LinkError) as ei:
            s2.connect(str(board.path), 115200)
        assert ei.value.code == "open_failed" and "占" in ei.value.message
    finally:
        s1.disconnect()
        s2.disconnect()


def test_wrong_ports(side, tmp_path):
    import tty
    st, mk = side
    ui = mk()
    r = ui.call("connect", port=str(tmp_path / "ttyNOPE"), baud="auto")
    assert not r["ok"] and r["error"]["code"] == "open_failed" and "找不到" in r["error"]["message"]
    r = ui.call("connect", port=str(tmp_path / "ttyNOPE"), baud=115200)
    assert not r["ok"] and "找不到" in r["error"]["message"] and han(r["error"]["fix"])

    m, s = os.openpty()                                           # 一声不吭的口（选错了 COM）
    tty.setraw(s)
    r = ui.call("connect", port=os.ttyname(s), baud="auto", timeout=40)
    assert not r["ok"] and r["error"]["code"] == "no_frames" and han(r["error"]["message"])

    stop = threading.Event()                                      # 只会 printf 的设备（视觉模块）

    def chatter():
        while not stop.is_set():
            try:
                os.write(m, b"x=12 y=34 ok\r\n")
            except OSError:
                pass
            time.sleep(0.02)
    threading.Thread(target=chatter, daemon=True).start()
    try:
        r = ui.call("connect", port=os.ttyname(s), baud="auto", timeout=40)
        assert not r["ok"] and r["error"]["code"] == "no_frames" and "原始" in r["error"]["fix"]
    finally:
        stop.set()
        os.close(m)
        os.close(s)


def test_garbage_on_line(board, side):
    from dzbench._dzlink import DATA, encode
    st, mk = side
    ui = mk()
    ui.ok("connect", port=str(board.path), baud="auto")
    ui.wait(lambda e: e["type"] == "schema")
    rnd = random.Random(1)
    for _ in range(400):
        board.inject(bytes(rnd.randrange(256) for _ in range(rnd.randrange(1, 40))))
        f = bytearray(encode(DATA, 2, 0, bytes(28)))
        f[rnd.randrange(3, len(f))] ^= 0xFF                      # CRC 坏的“像样”帧
        board.inject(bytes(f))
    time.sleep(0.5)
    stt = ui.ok("hello")["status"]
    assert stt["connected"] and stt["bad"] > 0
    assert "坏帧" in stt.get("hint", "")
    assert ui.ok("param_set", name="max_rps", value=3.5)["status"] == "ok", "乱码之后照常能调参"
    time.sleep(0.6)
    drive(ui, board)
