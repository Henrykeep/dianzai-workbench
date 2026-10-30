"""带负载回归（make estop-load）：所有核被占满时，急停 点击→latched、解除→cleared 的时延。

测试自己起一个占核子进程组（每核一个死循环），finally 里只终止自己起的那一组。
验收：≥50 次循环，两段时延的 p95 与最大值都 ≤ 200 ms；只发 'R'、通知每次只一次。
不在 make test 的默认收集目录里（tests/ 之外），由 make estop-load 显式跑；不 skip。
"""
from __future__ import annotations

import os
import pathlib
import signal
import statistics
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "tests"), str(HERE.parent)]
from wsui import UI, ServerThread  # noqa: E402

N = int(os.environ.get("ESTOP_LOAD_N", "50"))
LIMIT_MS = 200.0
BURN = r"""
import multiprocessing as mp, os, time
def spin():
    while True: pass
if __name__ == "__main__":
    ps = [mp.Process(target=spin, daemon=True) for _ in range(os.cpu_count() or 1)]
    [p.start() for p in ps]
    print("ready", flush=True)
    time.sleep(3600)
"""


def _pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def _arrival(ui, pred, start, timeout=10.0):
    e = ui.wait(pred, timeout, start)
    with ui.cv:
        return ui.rx_t[ui.events.index(e, start)]


def test_estop_latency_under_full_cpu_load(tmp_path, monkeypatch):
    monkeypatch.setenv("DZBENCH_HOME", str(tmp_path))
    burn = subprocess.Popen([sys.executable, "-c", BURN], stdout=subprocess.PIPE, text=True, start_new_session=True)
    try:
        assert burn.stdout.readline().strip() == "ready"
        st = ServerThread()
        ui = UI(st.port)
        try:
            ui.ok("connect", port="sim:car_2wd")
            ui.wait(lambda e: e.get("type") == "status" and e.get("alive"), 20)
            time.sleep(0.6)
            lat, clr = [], []
            for i in range(N):
                m = ui.mark(); t0 = time.monotonic()
                ui.ok("estop", src="负载回归")
                lat.append((_arrival(ui, lambda e: e.get("type") == "estop" and e.get("state") == "latched", m) - t0) * 1000)
                m = ui.mark(); t0 = time.monotonic()
                ui.ok("cmd", c="R")
                clr.append((_arrival(ui, lambda e: e.get("type") == "estop" and e.get("state") == "cleared", m) - t0) * 1000)
                ui.wait(lambda e: e.get("type") == "agent_notice" and e.get("blocker_code") == "estop_cleared", 10, m)
                time.sleep(0.05)
                assert sum(e.get("blocker_code") == "estop_cleared" for e in ui.events[m:]) == 1, i
                assert not st.srv.session.tx_locked
            rep = {k: {"p50": round(statistics.median(v), 1), "p95": round(_pct(v, .95), 1), "max": round(max(v), 1), "n": len(v)}
                   for k, v in (("click→latched", lat), ("R→cleared", clr))}
            print("ESTOP_LOAD", os.cpu_count(), "核满载", rep)
            for k, r in rep.items():
                assert r["n"] >= 50 and r["p95"] <= LIMIT_MS and r["max"] <= LIMIT_MS, (k, r)
        finally:
            ui.close(); st.stop()
    finally:
        os.killpg(burn.pid, signal.SIGTERM)   # 只终止自己起的那一组（start_new_session → 自己的进程组）
        burn.wait(10)
