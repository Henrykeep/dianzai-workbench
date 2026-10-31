"""r9q 快检回归：(a) 调参模式只剩 iterate_start；(d) 重复点“连接”不打断正在启动的仿真板；(f) 内置例题不要 PDF。"""
import threading
import time

from dzbench.agent import loop as loop_mod
from dzbench.session import Session
from dzbench.transport import LoopbackTransport


def test_tune_mode_only_iterate_path():
    tools = loop_mod.MODES["tune"]["tools"]
    assert "iterate_start" in tools and "iterate_cancel" in tools
    for old in ("tune_autopilot", "run_step_test", "propose_param_change", "rollback_best"):
        assert old not in tools, old
    assert "tune_autopilot / run_step_test" not in loop_mod.SYSTEM


def test_builtin_example_never_asks_pdf():
    assert "永远不要向用户要 PDF 路径" in loop_mod.SYSTEM


def test_concurrent_sim_connect_reuses(tmp_path):
    ev, opened = [], []

    def slow_open(port, baud):                     # 模拟首次连仿真板要先编译
        opened.append(port)
        time.sleep(0.4)
        return LoopbackTransport()
    s = Session(emit=ev.append, log_dir=tmp_path / "logs")
    s._open = slow_open
    out = []
    ts = [threading.Thread(target=lambda: out.append(s.connect("sim:2026H_ball", log=False))) for _ in range(2)]
    try:
        for t in ts:
            t.start()
            time.sleep(0.05)
        for t in ts:
            t.join(5)
        assert opened == ["sim:2026H_ball"], opened               # 第二次排队、复用，不拆掉重编
        assert sum(bool(r.get("reused")) for r in out) == 1, out
        st = [e for e in ev if e.get("type") == "sim_starting"]
        assert [e["state"] for e in st] == ["start", "ready"] and st[1]["elapsed_s"] >= 0.3, st
    finally:
        s.disconnect()
