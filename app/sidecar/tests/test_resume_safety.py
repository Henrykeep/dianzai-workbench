"""硬规则：侧车重启后的自动重连只恢复通信和遥测，绝不重发运行/运动命令或目标值。
在板子入口（pty → 固件 stdin）记下侧车发出的每一帧来断言，不信侧车自己的说法。"""
import os
import signal
import struct
import subprocess
import sys
import threading
import time

import pytest

from conftest import wd_timeout_ms
from dzbench._dzlink import DATA, HEARTBEAT, PARAM_SET, Parser, encode

pytestmark = pytest.mark.needs_sim
SIDECAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GO = struct.pack("<ff", 0.3, 0.0).hex()            # car_2wd 运动命令（DATA id 1）


def until(f, t=6.0):
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

    class Rec(PtyBoard):
        """额外记下侧车 → 板子的每一帧 (时间, kind, id, payload)。"""
        def _host_in(self, m):
            self.rx = getattr(self, "rx", [])
            p = Parser()
            while True:
                try:
                    b = os.read(m, 4096)
                except OSError:
                    return
                if not b:
                    return
                t = time.monotonic()
                self.rx.extend((t, k, i, pl) for k, i, _s, pl in p.feed(b))
                try:
                    self.proc.stdin.write(b)
                except (OSError, ValueError):
                    pass

    b = Rec("car_2wd", tmp_path / "ttyDZ0")
    yield b
    b.close()


def _start(home):
    from wsui import free_port, wait_port
    port = free_port()
    env = dict(os.environ, PYTHONPATH=SIDECAR, DZBENCH_HOME=str(home))
    p = subprocess.Popen([sys.executable, "-m", "dzbench", "--port", str(port)], env=env, cwd=SIDECAR,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_port(port)
    return p, port


def sp(board):
    tl = board.board_telem
    return tl if tl and time.monotonic() - board.board_t < 0.5 else None


def _forbidden(frames):
    """允许：上位机心跳、读参（PARAM_SET 空载荷）。其余（任何 DATA：运动/目标/命令/R/继电；带值的 PARAM_SET）都算违规。"""
    return [(k, i, pl.hex()) for _t, k, i, pl in frames
            if not (k == HEARTBEAT or (k == PARAM_SET and not pl))]


def _run_kill_restart(board, home, estop: bool):
    from wsui import UI
    p, port = _start(home)
    try:
        ui = UI(port)
        ui.ok("connect", port=str(board.path), baud="auto")
        wd_ms = wd_timeout_ms(ui.wait(lambda e: e["type"] == "schema"))
        time.sleep(0.6)
        ui.ok("send_data", id=1, hex=GO)                       # RUN：非零目标
        assert until(lambda: ((sp(board) or {}).get("sp_a") or 0) > 0.25), "命令应生效"
        if estop:
            ui.ok("estop")
            assert until(lambda: (sp(board) or {}).get("sp_a") == 0.0)
        ui.close()
        p.send_signal(signal.SIGKILL)
        p.wait()
        t_kill = time.monotonic()
        time.sleep(wd_ms / 1000 + 0.5)                          # 固件 wd_timeout_ms 没上位机心跳 → 急停并锁存
        safe = sp(board)
        p, port = _start(home)
        ui = UI(port)
        assert until(lambda: (ui.ok("hello")["link"] or {}).get("board") == "connected", 3.5), "3 s 内自动连回"
        time.sleep(2.0)                                         # 重连后的读参、心跳都跑完
        after = [f for f in board.rx if f[0] > t_kill]
        assert after, "重连后应有心跳/读参"
        assert _forbidden(after) == [], "自动重连发出了运动/目标/命令帧"
        tl = sp(board)
        assert tl and tl["sp_a"] == 0.0 and abs(tl["spd_a"]) < 0.05, f"板子不应在跑：{tl}"
        # 锁存：绕过侧车直接塞运动命令，板子仍不动
        board.proc.stdin.write(encode(DATA, 1, 0, bytes.fromhex(GO)))
        time.sleep(0.3)
        assert sp(board)["sp_a"] == 0.0, "急停应仍锁存，只有人点“解除急停”才解"
        ui.close()
        return safe
    finally:
        p.kill()


def test_resume_never_resends_run_or_setpoint(board, home):
    safe = _run_kill_restart(board, home, estop=False)
    assert safe and safe["sp_a"] == 0.0, f"侧车没了 1.5 s，固件应自己把目标归零：{safe}"


def test_resume_keeps_latched_estop(board, home):
    _run_kill_restart(board, home, estop=True)


def test_link_lost_stops_timed_sends():
    """会话内断线自动重连：定时/触发发送在断线时就停掉，重连后不会续发目标值。"""
    from dzbench.sender import Sender
    from dzbench.session import Session
    s = Session()
    snd = Sender(s)
    stopped = []
    snd.stop_all = lambda why="": stopped.append(why)
    s.emit({"type": "error", "code": "link_lost", "message": "x", "fix": ""})
    assert stopped == ["连接断开"]
