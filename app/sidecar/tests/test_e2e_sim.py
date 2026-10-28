"""侧车 ↔ host-sim（真实固件逻辑跑在 PC 上）端到端：无需硬件。"""
import asyncio
import json
import os
import shutil
import time

import pytest

from dzbench.session import Session

pytestmark = pytest.mark.skipif(os.name == "nt" or not shutil.which("make") or not shutil.which("cc"),
                                reason="host-sim --stream 需要 POSIX + make + cc")


def wait(cond, t=5.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < t:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("DZBENCH_HOME", str(tmp_path))
    return tmp_path


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
