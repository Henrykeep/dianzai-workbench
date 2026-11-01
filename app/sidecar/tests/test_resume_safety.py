"""硬规则：侧车重启后的自动重连只恢复通信和遥测，绝不重发运行/运动命令或目标值。
在板子入口（pty → 固件 stdin）记下侧车发出的每一帧来断言，不信侧车自己的说法。"""
import json
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


BOOT = ("import faulthandler,signal,sys,runpy;faulthandler.register(signal.SIGUSR1,file=sys.stderr,all_threads=True);"
        "sys.argv=['dzbench']+sys.argv[1:];runpy.run_module('dzbench',run_name='__main__')")


def _start(home, **env_extra):
    """侧车 stderr 落到 home/sidecar.err，并注册 SIGUSR1 → faulthandler（#155：卡住时 _stall_dump 取全部线程栈，CI 日志里留证据）。"""
    from wsui import free_port, wait_port
    port = free_port()
    env = dict(os.environ, PYTHONPATH=SIDECAR, DZBENCH_HOME=str(home), **env_extra)
    err = open(home / "sidecar.err", "ab")
    p = subprocess.Popen([sys.executable, "-c", BOOT, "--port", str(port)], env=env, cwd=SIDECAR,
                         stdout=subprocess.DEVNULL, stderr=err)
    err.close()
    wait_port(port)
    return p, port


def _stall_dump(p, home) -> str:
    """超时路径：打印测试进程全部线程栈（faulthandler.dump_traceback）+ 让侧车把全部线程栈写进 sidecar.err，返回给断言消息。"""
    import faulthandler
    print("=== test process stacks ===", file=sys.stderr)
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
    try:
        p.send_signal(signal.SIGUSR1)
        time.sleep(0.5)
    except OSError:
        pass
    try:
        return "\n=== sidecar stacks ===\n" + (home / "sidecar.err").read_text(errors="replace")[-12000:]
    except OSError:
        return ""


def _connected(ui, p, home, t):
    if until(lambda: (ui.ok("hello")["link"] or {}).get("board") == "connected", t):
        return True
    raise AssertionError(f"{t} s 内没自动连回：{ui.ok('hello')['link']}" + _stall_dump(p, home))


def sp(board):
    tl = board.board_telem
    return tl if tl and time.monotonic() - board.board_t < 0.5 else None


def _forbidden(frames):
    """允许：上位机心跳、读参（PARAM_SET 空载荷）、只读的握手信息查询 DATA 0x7E {'I'}（dzctl 0.17.0，恰好 1 字节 'I'，
    板子只回身份/哈希，不动作；重连后要重新问，可能换了板；急停位置位时侧车不发）。其余（任何 DATA：运动/目标/命令/R/继电；带值的 PARAM_SET）都算违规。"""
    return [(k, i, pl.hex()) for _t, k, i, pl in frames
            if not (k == HEARTBEAT or (k == PARAM_SET and not pl) or (k == DATA and i == 0x7E and pl == b"I"))]


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
        _connected(ui, p, home, 3.5)                            # 3 s 内自动连回（超时留双方线程栈）
        # #155：“已连接”只在上位机心跳真的发出后才报；这里再等心跳帧真的到板子（有上限，不固定睡）
        assert until(lambda: any(f[1] == HEARTBEAT for f in board.rx if f[0] > t_kill), 3.0), "连回后 3 s 内板子没收到上位机心跳"
        time.sleep(0.5)                                         # 再看一小段，确认没有运动/目标/命令帧
        after = [f for f in board.rx if f[0] > t_kill]
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


def test_sidecar_only_restart_board_latched_e2e(board, home):
    """只重启侧车、不重启 host-sim 板（PtyBoard 不动，真后端）：板上急停锁存（心跳 bit10）时新侧车不发 'I'，
    并按 bit10 自己锁存 tx_locked → 执行器操作立刻（远小于 2 s 上限）被 tx_locked 拒绝，不无限等、不当成旧固件，板子不动。
    注：estop_latched_ident_deferred 只在“bit10 仍置位但侧车未锁存”时出现；真后端里 bit10 一置位侧车就锁存、
    解除要等 bit10 清零才放开（_confirm_clear），所以该分支在真后端 + host-sim 上走不到，由单元测试覆盖。"""
    from wsui import UI
    p, port = _start(home)
    try:
        ui = UI(port)
        ui.ok("connect", port=str(board.path), baud="auto")
        wd_ms = wd_timeout_ms(ui.wait(lambda e: e["type"] == "schema"))
        time.sleep(0.6)
        ui.ok("estop")                                          # 板上急停锁存（心跳 bit10 置位）
        ui.close()
        p.send_signal(signal.SIGKILL)
        p.wait()
        t_kill = time.monotonic()
        time.sleep(wd_ms / 1000 + 0.5)
        p, port = _start(home)
        ui = UI(port)
        _connected(ui, p, home, 6.0)                            # 自动连回（超时留双方线程栈）
        assert until(lambda: any(f[1] == HEARTBEAT for f in board.rx if f[0] > t_kill), 3.0)
        t0 = time.monotonic()
        r = ui.call("send_data", id=1, hex=GO)
        dt = time.monotonic() - t0
        err = r.get("error") or r
        assert r["ok"] is False and err.get("code") == "tx_locked", r
        assert dt < 1.0, dt
        assert not any(k == DATA and i == 0x7E for _t, k, i, _pl in board.rx if _t > t_kill), "急停位在时不发 'I'"
        assert sp(board)["sp_a"] == 0.0
        ui.close()
    finally:
        p.kill()


def test_resume_no_response_latched_stall(board, home):
    """#160：急停锁存下只重启侧车，板子不回应（SIGSTOP host-sim）→ 超过 link.resume_bind_timeout_s（这里用声明式设置的
    环境变量覆盖成 1 s）没绑上 schema：link.state reason=resume_no_response + 中文、推 error 带 fix_action=reconnect，
    自动重握手一次；全程执行器被拒、不发 'I'/运动帧；板子恢复后连上，急停仍锁存（tx_locked）。"""
    from wsui import UI
    p, port = _start(home)
    try:
        ui = UI(port)
        ui.ok("connect", port=str(board.path), baud="auto")
        wd_ms = wd_timeout_ms(ui.wait(lambda e: e["type"] == "schema"))
        time.sleep(0.6)
        ui.ok("estop")
        ui.close()
        p.send_signal(signal.SIGKILL)
        p.wait()
        time.sleep(wd_ms / 1000 + 0.5)
        board.proc.send_signal(signal.SIGSTOP)               # 板子“没回应”
        t_kill = time.monotonic()
        p, port = _start(home, DZBENCH_RESUME_BIND_TIMEOUT_S="1.0")
        ui = UI(port)
        link = until(lambda: (lambda l: l if l.get("reason") == "resume_no_response" else None)(ui.ok("hello")["link"] or {}), 4.0)
        assert link, json.dumps(ui.ok("hello")["link"], ensure_ascii=False) + (home / "sidecar.err").read_text()[-3000:]
        assert link["board"] != "connected" and link.get("message_zh") == "重连后板子没有回应，请按『重新连接』", link
        ev = ui.wait(lambda e: e.get("code") == "resume_no_response", 4.0)
        assert ev["fix_action"] == "reconnect" and ev["message_zh"] == "重连后板子没有回应，请按『重新连接』"
        # 自动重握手一次：第二次超时 retrying=False（之后不再自动重来）
        ev2 = ui.wait(lambda e: e.get("code") == "resume_no_response" and e.get("retrying") is False, 6.0)
        assert ev2
        r = ui.call("send_data", id=1, hex=GO)
        assert r["ok"] is False or r.get("data") is False, json.dumps(r, ensure_ascii=False)   # 执行器全程被拒（或口已关、什么都没发）
        assert not any(k == DATA and i == 1 for _t, k, i, _pl in board.rx if _t > t_kill), "停滞期间不许有运动帧到板子"
        board.proc.send_signal(signal.SIGCONT)
        ui.ok("connect", port=str(board.path), baud="auto")   # 人点“重新连接”
        _connected(ui, p, home, 6.0)
        r = ui.call("send_data", id=1, hex=GO)
        assert r["ok"] is False and (r.get("error") or r).get("code") == "tx_locked", r   # 急停仍锁存
        assert _forbidden([f for f in board.rx if f[0] > t_kill]) == []
        time.sleep(0.3)
        assert sp(board)["sp_a"] == 0.0
        ui.close()
    finally:
        try:
            board.proc.send_signal(signal.SIGCONT)
        except OSError:
            pass
        p.kill()
