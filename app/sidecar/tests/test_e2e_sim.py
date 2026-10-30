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
        assert wait(lambda: s.schema and len(s.params) == len(s.schema.params))
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
        s.snapshot_save("pos", mode="position")        # 缺口第 3 项：环模式标签 + 平滑切换
        s.set_param("kp", 1.0)
        sent = []
        orig = s.set_param
        s.set_param = lambda k, v, verify=False: (sent.append((k, v)), orig(k, v, verify))[1]
        s.snapshot_restore("pos", ramp_s=0.25)
        s.set_param = orig
        ks = [v for k, v in sent if k == "kp"]
        assert len(ks) == 5 and ks[0] < 1.0 and ks[-1] == pytest.approx(0.08) and ks == sorted(ks, reverse=True)
        assert s.read_param("kp") == pytest.approx(0.08)
        from dzbench import snapshots
        assert next(x for x in snapshots.list_all(s.schema.hash) if x["name"] == "pos")["mode"] == "position"
        with pytest.raises(Exception):
            s.snapshot_save("x", mode="bogus")
    finally:
        s.disconnect()


def test_readback_fw_rev_and_last_good_diff(home, tmp_path):
    """dzctl 0.4.0：心跳带固件版本；全量回读写 params.txt；params_diff 与 last-good 对比。"""
    import subprocess
    import sys
    from dzbench.session import fw_rev_str
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    s = Session()
    s.connect("sim:car_2wd")
    try:
        assert wait(lambda: s.schema and len(s.params) == len(s.schema.params) and s.fw_rev)
        head = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
        if head:
            assert fw_rev_str(s.fw_rev).startswith(head), (fw_rev_str(s.fw_rev), head)
        assert s.status()["fw_rev"] == fw_rev_str(s.fw_rev)
        good = s.export_readback(tmp_path / "last_good.txt")
        txt = open(good, encoding="utf-8").read()
        assert "fw_rev = " + fw_rev_str(s.fw_rev) in txt and "kp = 0.08\n" in txt
        s.set_param("kp", 0.3)
        now = s.export_readback(tmp_path / "now.txt")
    finally:
        s.disconnect()
    tool = os.path.join(repo, "tools", "params_diff.py")
    same = subprocess.run([sys.executable, tool, good, good], capture_output=True, text=True)
    assert same.returncode == 0 and "完全一致" in same.stdout
    r = subprocess.run([sys.executable, tool, good, now], capture_output=True, text=True)
    assert r.returncode == 1 and "~ kp: 0.08 → 0.3" in r.stdout and "共 1 处" in r.stdout, r.stdout


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
            assert p["ok"] and p["data"][0]["status"] == "pending_user_confirmation"
            assert srv.session.params["kp"] == pytest.approx(0.08), "提议不能直接生效"
            d = await rpc(op="proposal_decide", id=p["data"][0]["id"], accept=True)
            assert d["ok"] and d["data"]["applied"] == 2.0
            # 提议路径统一：一组 changes、同一种卡；来源写在卡上
            pg = await rpc(op="propose", changes={"kp": 1.5, "ki": 0.2}, reason="分析阶跃", source="规则")
            assert pg["ok"] and len(pg["data"]) == 2
            for c in pg["data"]:
                await rpc(op="proposal_decide", id=c["id"], accept=False)
            # 回到… 统一 params_restore：固件默认 / 某个快照 / 最好一轮（侧车刚起没有最好一轮 → 中文错误）
            r = await rpc(op="params_restore", source="default")
            assert r["ok"] and r["data"]["source"] == "default"
            assert srv.session.params["kp"] == pytest.approx(0.08)
            await rpc(op="param_set", name="kp", value=1.2)
            assert (await rpc(op="snapshot_save", name="t"))["ok"]
            await rpc(op="param_set", name="kp", value=0.5)
            r = await rpc(op="params_restore", source="snapshot", name="t")
            assert r["ok"] and srv.session.params["kp"] == pytest.approx(1.2)
            nb = await rpc(op="params_restore", source="best")
            assert not nb["ok"] and nb["error"]["code"] == "no_best"
            from dzbench import snapshots
            snapshots.save(srv.session.schema.hash, srv.svc.BEST_SNAPSHOT, {**srv.session.params, "kp": 0.7})
            r = await rpc(op="params_restore", source="best")       # 护栏没记录 → 用自动存的最好一轮快照
            assert r["ok"] and r["data"]["source"] == "snapshot" and srv.session.params["kp"] == pytest.approx(0.7)
            assert (await rpc(op="params_restore", source="yesterday"))["error"]["code"] == "bad_arg"
            assert not (await rpc(op="snapshot_restore", name="t"))["ok"], "旧 op 已合并"
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
        assert wait(lambda: s.schema and len(s.params) == len(s.schema.params))
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


def test_step_in_window_is_pure_data():
    """评测等阶跃用板子时间判定：没跳变 / 刚跳 / 保持够久。"""
    from dzbench.agent.evals import step_in_window
    mk = lambda pts: [(t, {"sp": v}) for t, v in pts]
    assert not step_in_window(mk([(i * 0.1, 0.0) for i in range(30)]), "sp", 1.0)
    assert not step_in_window(mk([(i * 0.1, 0.0 if i < 25 else 2.0) for i in range(30)]), "sp", 1.0)
    assert step_in_window(mk([(i * 0.1, 0.0 if i < 10 else 2.0) for i in range(30)]), "sp", 1.0)
    assert step_in_window(mk([(i * 0.1, 5.0 if i < 10 else -1.0) for i in range(30)]), "sp", 1.0)
