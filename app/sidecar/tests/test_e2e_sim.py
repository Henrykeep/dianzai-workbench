"""侧车 ↔ host-sim（真实固件逻辑跑在 PC 上）端到端：无需硬件。"""
import asyncio
import json
import os
import shutil
import time

import pytest

from dzbench.session import Session

pytestmark = pytest.mark.needs_sim  # 原 skipif 条件统一放在 conftest.SIM_OK


def wait(cond, t=5.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < t:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_car_2wd_params(home):
    s = Session()
    s.connect("sim:car_2wd")
    try:
        assert wait(lambda: s.schema and len(s.params) == 5)
        assert s.params["kp"] == pytest.approx(0.08)
        assert wait(lambda: len(s.window(1)) > 10)
        r = s.set_param("kp", 9)
        assert r["applied"] == 2.0 and r["status"] == "clamped"
        assert s.read_param("kp") == 2.0
        s.snapshot_save("hot")
        s.set_param("kp", 0.3)
        s.snapshot_restore("hot")
        assert s.read_param("kp") == 2.0
        s.snapshot_restore(defaults=True)
        assert s.read_param("kp") == pytest.approx(0.08)
    finally:
        s.disconnect()


def test_2026h_estop_and_replay(home):
    s = Session()
    s.connect("sim:2026H_ball")
    log = s.status()["log"]
    try:
        assert wait(lambda: s.schema and s.window(1))
        assert s.estop()["sent"]
        assert wait(lambda: s.window(0.1) and s.window(0.1)[-1][1]["state"] == 3), "state 应变为 ESTOP"
        n_live = len(s.samples)
    finally:
        s.disconnect()
    r = Session()
    r.connect("replay:" + log, log=False)
    try:
        assert wait(lambda: r.tr.done, 15)
        assert r.schema and abs(len(r.samples) - n_live) <= 2
        assert r.samples[-1][1]["state"] == 3
        assert r.estop()["sent"] is False
    finally:
        r.disconnect()


def test_websocket_server(home):
    websockets = pytest.importorskip("websockets")
    from dzbench.server import Server

    async def run():
        srv = Server()
        task = asyncio.ensure_future(srv.serve("127.0.0.1", 18765))
        await asyncio.sleep(0.3)
        async with websockets.connect("ws://127.0.0.1:18765") as ws:
            async def rpc(**m):
                await ws.send(json.dumps(m | {"rid": m["op"]}))
                while True:
                    x = json.loads(await ws.recv())
                    if x.get("type") == "reply" and x["rid"] == m["op"]:
                        return x
            assert any(p["port"] == "sim:car_2wd" for p in (await rpc(op="hello"))["data"]["ports"])
            assert (await rpc(op="connect", port="sim:car_2wd"))["ok"]
            got = set()
            t0 = time.monotonic()
            while not {"telem", "status", "schema"} <= got and time.monotonic() - t0 < 6:
                got.add(json.loads(await ws.recv())["type"])
            assert {"telem", "status", "schema"} <= got
            await asyncio.sleep(0.5)
            p = await rpc(op="propose", name="kp", value=7, reason="test")
            assert p["ok"] and p["data"]["status"] == "pending_user_confirmation"
            assert srv.session.params["kp"] == pytest.approx(0.08), "提议不能直接生效"
            d = await rpc(op="proposal_decide", id=p["data"]["id"], accept=True)
            assert d["ok"] and d["data"]["applied"] == 2.0
            bad = await rpc(op="param_set", name="nope", value=1)
            assert not bad["ok"] and bad["error"]["code"] == "bad_param"
            assert (await rpc(op="estop"))["data"]["sent"]
            await rpc(op="disconnect")
        task.cancel()

    asyncio.run(asyncio.wait_for(run(), 30))


def test_tune_analyze_on_sim_step(home, tmp_path):
    """真实固件闭环（host-sim car_2wd）上做阶跃 → 离线规则分析 → 写回 yaml 的 diff（不落盘）。"""
    import struct
    from dzbench.agent.service import AgentService
    from dzbench.agent_api import AgentTools
    s = Session()
    s.connect("sim:car_2wd")
    try:
        assert wait(lambda: s.schema and len(s.params) == 5)
        t_end = time.monotonic() + 2.0
        while time.monotonic() < t_end:            # 0.6 s 静止后阶跃到 3 r/s，持续发（cmd_timeout 200 ms）
            v = 0.0 if t_end - time.monotonic() > 1.4 else 3.0
            s.send_data(1, struct.pack("<ff", v, v))
            time.sleep(0.05)
        ev = []
        svc = AgentService(s, AgentTools(s, ev.append), ev.append, root=tmp_path)
        r = svc.step_analysis(seconds=2.0)
        assert (r["y"], r["sp"]) == ("spd_a", "sp_a") and r["gains"]["kp"] == "kp"
        m = r["metrics"]
        assert m["ok"] and m["target"] > 0.5, m
        assert r["hints"] and all("text" in h for h in r["hints"])
    finally:
        s.disconnect()


def test_host_heartbeat_watchdog_latches_estop(home):
    """侧车心跳停了（模拟崩溃）> 1 s：car_2wd 固件输出归零并锁存急停；R 解除后才恢复。"""
    import struct
    s = Session()
    s.connect("sim:car_2wd")
    try:
        assert wait(lambda: s.schema)
        time.sleep(0.6)                                   # 至少一帧上位机心跳 -> 看门狗布防
        sp = lambda: s.window(0.1)[-1][1]["sp_a"] if s.window(0.1) else None  # noqa: E731
        s.send_data(1, struct.pack("<ff", 0.3, 0.0))
        assert wait(lambda: (sp() or 0) > 0.5), "命令应生效"
        s.host_hb = False
        time.sleep(1.6)                                   # cmd_timeout 也会停车，所以下面再发命令验证"锁存"
        s.send_data(1, struct.pack("<ff", 0.3, 0.0))
        time.sleep(0.3)
        assert sp() == 0.0, "看门狗触发后应锁存急停，命令被拒"
        s.host_hb = True
        s.cmd("R")
        time.sleep(0.1)
        s.send_data(1, struct.pack("<ff", 0.3, 0.0))
        assert wait(lambda: (sp() or 0) > 0.5), "R 解除后恢复"
    finally:
        s.disconnect()


def test_2026h_imu_module_path(home):
    """仿真里有 IMU 姿态模块（sim_setup 200 Hz 发 dzimu）：io 层解出来 → 遥测 imu_ok=1，imu_axis 参数可调。"""
    s = Session()
    s.connect("sim:2026H_ball")
    try:
        assert wait(lambda: s.schema and s.window(1))
        assert wait(lambda: s.window(0.2) and s.window(0.2)[-1][1].get("imu_ok") == 1), "IMU 帧应被解出"
        assert wait(lambda: s.params.get("imu_axis") == 0), "参数表应含 imu_axis"
        assert abs(s.window(0.2)[-1][1]["imu_ax_mps2"]) < 0.2   # 静止且模块俯仰 3°：去重力后前向加速度≈0
        assert s.set_param("imu_grav_comp", 0)["status"] == "ok"
        time.sleep(0.3)
        assert -0.7 < s.window(0.1)[-1][1]["imu_ax_mps2"] < -0.3   # 不去重力：≈ −g·sin3°
        r = s.set_param("imu_axis", 9)
        assert r["applied"] == 5 and r["status"] == "clamped"
    finally:
        s.disconnect()


def test_agent_evals_offline_sim(home):
    """没填 Key：问 Agent 走离线规则助手，评测集在 car_2wd 仿真板上全部通过（真跑工具，不是假 transcript）。"""
    from dzbench.agent import evals
    res = evals.run_sim("sim:car_2wd", log=lambda *_: None)
    assert res and all(r["mode"] == "离线规则助手" for r in res)
    assert [r["id"] for r in res if not r["ok"]] == [], [(r["id"], r["why"]) for r in res if not r["ok"]]


def test_agent_evals_offline_sim_2026h(home):
    """同一套评测在 2026H 球杆仿真（假 QD4310 + 球物理）上也全部通过：按对象选阶跃配置，调参建议落到 pos_k 而不是底盘 kp。"""
    from dzbench.agent import evals
    res = evals.run_sim("sim:2026H_ball", log=lambda *_: None)
    assert [r["id"] for r in res if not r["ok"]] == [], [(r["id"], r["why"]) for r in res if not r["ok"]]
    tune = next(r for r in res if r["id"] == "one_gain_per_round")
    assert "pos_k" in tune["text"] and "chassis_kp" not in tune["text"]
