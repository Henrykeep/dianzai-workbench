"""Agent 烧录全流程端到端（假 pyOCD + pty 仿真板）：编译 → 请求烧录 → 人确认 → dry_run 计划 → 烧录 → 复位后心跳哈希核对 → 回滚。

走的都是真代码：WebSocket 服务、风险网关、AgentLoop、keil.build（假 UV4 脚本）、Flasher、PyOCDBackend（假 pyocd 包）、
pyserial 读 pty。“芯片”换固件 = 仿真板换应用重启，所以哈希核对是真的在看板子跑的是什么。真探针 【未测】。
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.needs_sim  # 原 skipif 条件统一放在 conftest.SIM_OK

HERE = os.path.dirname(__file__)

FAKE_UV4 = r'''#!{py}
"""假 Keil UV4：UV4 -b <proj> -j0 -o <log>。编出来的“镜像”内容 = 环境变量 FAKE_FW 指定的仿真应用名。"""
import os, pathlib, shutil, sys
a = sys.argv
proj = pathlib.Path(a[a.index("-b") + 1]); log = pathlib.Path(a[a.index("-o") + 1])
root = proj.parent
fw, sch = os.environ["FAKE_FW"], os.environ.get("FAKE_SCHEMA_APP", os.environ["FAKE_FW"])
(root / "fw.bin").write_bytes(fw.encode())
shutil.copy(pathlib.Path(os.environ["SIM_BUILD"]) / sch / "linkgen/link_schema.json", root / "link_schema.json")
log.write_text('Program Size: Code=100 RO-data=0 RW-data=0 ZI-data=0\n"fw.axf" - 0 Error(s), 0 Warning(s).\n', encoding="utf-8")
'''


@pytest.fixture
def rig(home, tmp_path, monkeypatch):
    from ptyboard import PtyBoard
    from dzbench.transport import ROOT
    monkeypatch.syspath_prepend(os.path.join(HERE, "fakepyocd"))
    for k in [m for m in sys.modules if m == "pyocd" or m.startswith("pyocd.")]:
        monkeypatch.delitem(sys.modules, k)
    import pyocd
    repo = tmp_path / "proj"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "p.uvprojx").write_text("", encoding="utf-8")
    uv4 = tmp_path / "UV4"
    uv4.write_text(FAKE_UV4.replace("{py}", sys.executable), encoding="utf-8")
    uv4.chmod(uv4.stat().st_mode | stat.S_IEXEC)
    (repo / "dzbench.json").write_text(json.dumps({
        "build": {"keil_uv4": str(uv4), "keil_project": "p.uvprojx", "image": "fw.bin", "link_schema": "link_schema.json"},
        "flash": {"target": "mspm0g3507", "heartbeat_timeout_s": 6}}), encoding="utf-8")
    monkeypatch.setenv("SIM_BUILD", str(ROOT / "build/host-sim"))
    board = PtyBoard("car_2wd", tmp_path / "ttyDZ0")
    PtyBoard("2026H_ball", tmp_path / "ttyWARM").close()           # 先编好第二个应用，烧录时不用等 make
    pyocd.BOARD, pyocd.FLASH[:], pyocd.LOG[:] = board, bytearray(b"car_2wd"), []
    yield repo, board, pyocd
    pyocd.BOARD = None
    board.close()


def test_agent_flash_full_flow(rig, monkeypatch):
    from agentfake import FakeLLM, call
    from dzbench.agent.service import AgentService
    from wsui import UI, ServerThread
    repo, board, pyocd = rig
    st = ServerThread()
    srv = st.srv
    llm = FakeLLM([
        {"role": "assistant", "content": None, "tool_calls": [call("build")]},
        {"role": "assistant", "content": None, "tool_calls": [call("flash", dry_run=False)]},   # 模型想直接真烧 → 只会出确认卡
        {"role": "assistant", "content": "编译通过，烧录等你确认。"},
    ])
    srv.svc = AgentService(srv.session, srv.agent, srv.emit, root=repo, llm=llm)
    ui = UI(st.port)
    try:
        ui.ok("hello")
        ui.ok("connect", port=str(board.path), baud="auto")
        ui.wait(lambda e: e["type"] == "schema")
        car_hash = srv.session.schema_hash
        assert car_hash == board.board_hash

        # 1) 没按急停：Agent 编译 → 请求烧录 → 卡片预览里直接说明前置条件不满足
        monkeypatch.setenv("FAKE_FW", "car_2wd")
        m = ui.mark()
        assert "等你确认" in ui.ok("agent_ask", text="编译并烧录", timeout=30)
        card = ui.wait(lambda e: e["type"] == "agent_action", start=m)
        assert card["tool"] == "flash" and "急停" in card["preview"]["error"] and card["sim"] is False
        assert not [x for x in pyocd.LOG if x[0] == "program"], "确认前不能动芯片"
        ui.ok("agent_action_decide", id=card["id"], accept=False)          # 拒绝

        # 2) 按急停，界面“烧录…”按钮：卡片里是 dry_run 计划；点执行 → 烧录 → 复位 → 心跳核对通过
        ui.ok("estop")
        m = ui.mark()
        assert ui.ok("flash")["status"] == "pending_human_click"
        card = ui.wait(lambda e: e["type"] == "agent_action", start=m)
        pv = card["preview"]
        assert pv["status"] == "dry_run" and pv["image"].endswith("fw.bin") and pv["base"] == "0x00000000"
        assert all(p["ok"] for p in pv["preconditions"])
        assert not [x for x in pyocd.LOG if x[0] == "program"]
        r = ui.ok("agent_action_decide", id=card["id"], accept=True, timeout=30)["result"]
        assert r["status"] == "flashed" and r["verify"]["ok"] is True and r["verify"]["schema_hash"] == f"{car_hash:08X}"
        assert ("program", str(repo / "fw.bin"), 0) in pyocd.LOG and ("reset",) in pyocd.LOG
        assert open(r["backup"], "rb").read() == b"car_2wd"

        # 3) 编了个错工程（镜像是 2026H，但 link_schema 是 car_2wd）：烧完心跳哈希不符 → 提示回滚
        monkeypatch.setenv("FAKE_FW", "2026H_ball")
        monkeypatch.setenv("FAKE_SCHEMA_APP", "car_2wd")
        b = ui.ok("build", timeout=30)
        assert b["ok"] and b["flash_ready"] is True
        m = ui.mark()
        ui.ok("flash")
        card = ui.wait(lambda e: e["type"] == "agent_action", start=m)
        r = ui.ok("agent_action_decide", id=card["id"], accept=True, timeout=30)["result"]
        assert r["verify"]["ok"] is False and "回滚" in r["verify"]["fix"]
        assert board.app == "2026H_ball" and board.board_hash != car_hash

        # 4) 回滚固件：也要确认；回滚后按“烧之前那版”的哈希核对
        m = ui.mark()
        assert ui.ok("flash_rollback")["status"] == "pending_human_click"
        card = ui.wait(lambda e: e["type"] == "agent_action", start=m)
        assert card["tool"] == "flash_rollback" and card["preview"]["status"] == "dry_run"
        r = ui.ok("agent_action_decide", id=card["id"], accept=True, timeout=30)["result"]
        assert r["status"] == "rolled_back" and r["verify"]["ok"] is True
        assert board.app == "car_2wd" and srv.session.schema_hash == car_hash

        # 审计日志里每一步都有
        audit = (srv.svc.gw.root, open(os.path.join(os.environ["DZBENCH_HOME"], "agent_audit.jsonl"), encoding="utf-8").read())[1]
        assert audit.count('"flash"') >= 3 and "rejected" in audit and "flash_rollback" in audit
    finally:
        ui.close()
        st.stop()


def test_verify_needs_fresh_heartbeat(rig):
    """板子复位后没起来：不能拿复位前的旧心跳当“校验通过”（以前的漏洞）。"""
    from dzbench import config
    from dzbench.flash import Flasher
    from dzbench.session import Session
    repo, board, pyocd = rig
    s = Session()
    s.connect(str(board.path), 115200, log=False)
    try:
        t0 = time.monotonic()
        while s.schema_hash is None and time.monotonic() - t0 < 5:
            time.sleep(0.05)
        f = Flasher(s, config.load(repo))
        f.note_build(True, __file__, s.schema_hash)
        board.proc.kill()                                  # 板子“死了”：再也没有心跳
        time.sleep(0.1)
        assert f.verify(timeout=0.6, after=time.monotonic())["ok"] is False
        assert f.verify(timeout=0.2)["ok"] is True, "不传 after 时还是老行为（给手动“校验”按钮用）"
    finally:
        s.disconnect()
