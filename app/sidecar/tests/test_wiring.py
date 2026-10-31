"""“真的接上了吗”：界面每个按钮发的 op 侧车都认；侧车每个 op 都有人调（界面按钮或写明的脚本接口）；
Agent 每个工具都有实现和风险等级，human 级的在确认卡上有中文名；新加的按钮走一遍 UI → 侧车 → 仿真板 → 回来。
功能 → 测试对照表见 docs/23 §v0.8.0。"""
import json
import pathlib
import re
import subprocess

import pytest

APP = pathlib.Path(__file__).resolve().parents[2]
UI_SRC = "\n".join(p.read_text(encoding="utf-8") for p in (APP / "ui/src").glob("*.ts"))
SERVER_OPS = set(re.findall(r'op == "([a-z_.]+)"', (APP / "sidecar/dzbench/server.py").read_text(encoding="utf-8")))
# 不在界面上、故意保留的 op（脚本 / 测试接口）：单一来源 = docs/dev/entrypoints.yaml script_ops
import yaml  # noqa: E402
SCRIPT_ONLY = yaml.safe_load((APP.parent / "docs/dev/entrypoints.yaml").read_text(encoding="utf-8"))["script_ops"]


def ui_ops():
    return set(re.findall(r'(?:rpc|call|fire)(?:<[^>]*>)?\(\s*"([a-z_.]+)"', UI_SRC))


def test_every_ui_op_is_served():
    missing = ui_ops() - SERVER_OPS
    assert not missing, f"界面调了侧车不认识的 op：{missing}"


def test_every_server_op_has_a_caller():
    # 进度条的修复按钮按 fix_action 生成（dzbench/progress.py FIX → entrypoints.yaml 里同名动作；位置已固定登记，不再靠 dynamic）
    from dzbench.progress import FIX
    acts = yaml.safe_load((APP.parent / "docs/dev/entrypoints.yaml").read_text(encoding="utf-8"))["actions"]
    from dzbench.human_only import GOTO                    # human_only 错误的 fix_action（如 enable_cloud）：Agent 错误卡按它跳到界面入口
    fix_ops = {op for a in acts if a["id"] in FIX.values() or a["id"] in GOTO or a.get("ready") is False for op in a.get("ops") or []}   # ready:false = 已登记、界面待接
    orphan = SERVER_OPS - ui_ops() - set(SCRIPT_ONLY) - fix_ops
    assert not orphan, f"侧车 op 没有界面入口也没写进 SCRIPT_ONLY：{orphan}"
    assert not (set(SCRIPT_ONLY) - SERVER_OPS), "SCRIPT_ONLY 里有已删掉的 op"


def test_every_agent_tool_wired():
    from dzbench.agent import cards, risk
    from dzbench.agent.loop import TOOLS
    from dzbench.agent.service import AgentService
    from dzbench.agent_api import AgentTools
    from dzbench.session import Session
    s = Session()
    svc = AgentService(s, AgentTools(s, lambda e: None), lambda e: None)
    names = {t["name"] for t in TOOLS}
    assert names == set(svc.loop.handlers), f"工具表和实现对不上：{names ^ set(svc.loop.handlers)}"
    cn = set(re.findall(r"(\w+): \"", re.search(r"TOOL_CN[^{]*\{([^}]*)\}", UI_SRC).group(1)))
    for n in names:
        t = risk.tier(n, False)
        assert t in (risk.AUTO, risk.LOG, risk.HUMAN), n
        if t == risk.HUMAN:
            assert n in cn or n in cards.TITLED, f"human 级工具 {n} 在确认卡上没有中文名（agent.ts TOOL_CN 或卡片 title）"


@pytest.fixture
def rig(home, tmp_path):
    from dzbench.agent.service import AgentService
    from wsui import UI, ServerThread
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "dzbench.json").write_text(json.dumps({"step_test": {"kind": "data", "id": 1, "fmt": "<ff", "low": [0, 0],
        "high": [0.4, 0], "hold_s": 1.0, "pre_s": 0.4, "y": "spd_a", "sp": "sp_a"}}), encoding="utf-8")
    st = ServerThread()
    st.srv.svc = AgentService(st.srv.session, st.srv.agent, st.srv.emit, root=tmp_path)
    ui = UI(st.port)
    ui.ok("connect", port="sim:car_2wd")
    ui.wait(lambda e: e["type"] == "schema")
    yield st, ui, tmp_path
    ui.close()
    st.stop()


@pytest.mark.needs_sim
def test_v08_buttons_e2e(rig):
    """v0.8.0 新接上的按钮：自动重连开关、阶跃实验、规则建议、重置护栏、新对话。"""
    st, ui, _ = rig
    assert ui.ok("auto_reconnect", on=False) == {"on": False} and st.srv.session.auto_reconnect is False
    ui.ok("auto_reconnect", on=True)
    m = ui.mark()
    ui.ok("tune_step_test", timeout=30)
    r = ui.wait(lambda e: e["type"] == "tune_round", start=m)
    assert r["verdict"]["round"] == 1 and r["metrics"]["ok"]
    out = ui.ok("tune_rule_round")
    assert out.get("status") == "pending_user_confirmation" or out.get("action") == "OBSERVE"
    ui.ok("tune_reset")
    ui.ok("tune_step_test", timeout=30)
    assert ui.wait(lambda e: e["type"] == "tune_round", start=m + 1 + [e["type"] for e in ui.events[m:]].index("tune_round"))["verdict"]["round"] == 1, "重置护栏后从第 1 轮算"
    st.srv.svc.loop.messages.append({"role": "user", "content": "旧问题"})
    ui.ok("agent_reset")
    assert len(st.srv.svc.loop.messages) <= 1, "新对话要清掉上下文"


@pytest.mark.needs_sim
def test_agent_tools_via_ui(rig):
    """在 Agent 面板里提问 → 模型调工具 → 侧车执行 → 结果回到对话（假模型，真链路、真仿真板）。"""
    from agentfake import FakeLLM, call
    from dzbench.agent.service import AgentService
    st, ui, repo = rig
    (repo / "notes.md").write_text("# hi\n", encoding="utf-8")
    calls = [call("read_telemetry", seconds=1), call("list_params"), call("list_files", glob="*.md"),
             call("read_file", path="notes.md"), call("tune_context"), call("observe", reason="看看"),
             call("run_step_test"), call("step_analysis", y="spd_a", sp="sp_a"),
             call("propose_param_change", name="kp", value=0.09, reason="测"), call("rollback_best"),
             call("decode_hardfault", frame=[0, 0, 0, 0, 0, 0x08000101, 0x08000100, 0x01000000])]
    llm = FakeLLM([{"role": "assistant", "content": None, "tool_calls": calls[i:i + 4]} for i in range(0, len(calls), 4)] + [{"role": "assistant", "content": "好了"}])
    st.srv.svc = AgentService(st.srv.session, st.srv.agent, st.srv.emit, root=repo, llm=llm)
    m = ui.mark()
    assert ui.ok("agent_ask", text="全都试一遍", timeout=60) == "好了"
    ui.wait(lambda e: e["type"] == "agent_tool" and e["name"] == "decode_hardfault", start=m)   # 工具事件可能比回答晚到
    seen = {e["name"]: e["ok"] for e in ui.events[m:] if e["type"] == "agent_tool"}
    bad = {n for n, ok in seen.items() if not ok}
    assert set(seen) >= {c["function"]["name"] for c in calls} - {"rollback_best"}, seen
    assert not bad - {"rollback_best"}, f"工具执行失败：{bad}"          # rollback_best 没有“最好一轮”时可以合理地失败
    assert any(e["type"] == "proposal" for e in ui.events[m:]), "提议参数要出卡片"


@pytest.mark.needs_sim
def test_car_firmware_options_e2e(rig):
    """固件选项（car_2wd 的 app.yaml params）：界面改参数 → 板子行为真的变了（看板子遥测）。"""
    import struct
    import time
    st, ui, _ = rig
    s = st.srv.session
    sp = lambda: s.window(0.1)[-1][1]["sp_a"] if s.window(0.1) else None  # noqa: E731
    go = lambda v: ui.ok("send_data", id=1, hex=struct.pack("<ff", v, 0.0).hex())  # noqa: E731

    def settle(t):
        end = time.monotonic() + t
        while time.monotonic() < end:
            go(0.3)
            time.sleep(0.05)
    time.sleep(0.6)
    settle(1.0)
    full = sp()
    assert full > 0.5
    ui.ok("param_set", name="max_rps", value=0.4)                 # 限速
    settle(1.0)
    assert sp() <= 0.4 + 1e-3, sp()
    ui.ok("param_set", name="max_rps", value=5.0)
    ui.ok("param_set", name="accel_rps2", value=0.5)              # 加速度限幅：从 0 起步很慢
    go(0.0)
    time.sleep(0.8)
    ui.ok("param_set", name="cmd_timeout_ms", value=2000)
    go(0.3)
    time.sleep(0.4)
    assert 0 < sp() < 0.35, sp()
    ui.ok("param_set", name="accel_rps2", value=100)
    go(0.3)
    time.sleep(0.6)                                                # 2 s 超时：不连续发命令也还在走
    assert sp() > 0.5
    ui.ok("param_set", name="cmd_timeout_ms", value=50)           # 断线停车
    go(0.3)
    time.sleep(0.4)
    assert sp() == 0.0, sp()
