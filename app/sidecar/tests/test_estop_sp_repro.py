"""#43 复现：motor_pos 阶跃实验进行中急停 → 0.5 s 后解除 R，查本地服务在 R 前后有没有再下发设定值（DATA id=1）。
在 Session._send 这一层记下所有发出的帧（不管来源：阶跃实验、调参循环、重连恢复、队列残留，最后都走这里），
并核对解除后板上 sp_deg 是否为 0。次数 DZ_REPRO_N（默认 5；排查时跑 ≥50）。"""
import os
import struct
import threading
import time

import pytest

from dzbench.agent.service import AgentService
from dzbench.agent_api import AgentTools
from dzbench.session import Session

pytestmark = pytest.mark.needs_sim
N = int(os.environ.get("DZ_REPRO_N", "5"))


def wait(cond, t=10.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < t:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_no_setpoint_after_clear(home):
    s = Session()
    s.connect("sim:motor_pos")
    tx, orig = [], s._send

    def spy(kind, id_, payload=b""):
        ok = orig(kind, id_, payload)
        tx.append((time.monotonic(), id_, bytes(payload), threading.current_thread().name))
        return ok
    s._send = spy
    res = []
    try:
        assert wait(lambda: s.schema and len(s.window(0.5)) > 5, 30)
        svc = AgentService(s, AgentTools(s, lambda e: None), lambda e: None)
        for i in range(N):
            err = []
            th = threading.Thread(target=lambda: err.append(_run(svc)), name="step")
            th.start()
            time.sleep(0.8)
            assert s.window(0.2)[-1][1]["sp_deg"] == 90.0
            s.estop("repro")
            time.sleep(0.5)
            t_board_r = s.window(0.01)[-1][0]          # 发 R 时最新样本的板子时间
            t_r = time.monotonic()
            s.cmd("R")
            stale = [v["sp_deg"] for _, v in s.window(0.25)]      # 发 R 后马上读到的最近一批遥测（R 之前采的）
            assert wait(lambda: not s.tx_locked, 3), "R 后没收到 bit10=0 心跳"
            th.join(5)
            time.sleep(1.0)
            after = [v["sp_deg"] for t, v in s.window(2.0) if t > t_board_r + 0.05]
            sp_tx_after_r = [x for x in tx if x[0] > t_r and x[1] == 1]
            res.append({"i": i, "stale_has_90": 90.0 in stale, "after_max": max(map(abs, after)),
                        "sp_tx_after_r": len(sp_tx_after_r), "step_err": err[0] if err else None})
            assert not sp_tx_after_r, f"第 {i} 轮：R 之后本地服务又发了设定值 {sp_tx_after_r}"
            assert after and max(map(abs, after)) == 0.0, f"第 {i} 轮：解除后 sp_deg 非零 {after[:5]}"
            time.sleep(0.3)
    finally:
        s.disconnect()
        if os.environ.get("DZ_REPRO_OUT"):
            import json
            with open(os.environ["DZ_REPRO_OUT"], "w") as f:
                json.dump(res, f, ensure_ascii=False, indent=1)


def _run(svc):
    try:
        svc.run_step_test()
        return "finished"
    except Exception as e:  # noqa: BLE001  急停后实验应被 tx_locked 打断
        return f"{type(e).__name__}: {getattr(e, 'code', e)}"
