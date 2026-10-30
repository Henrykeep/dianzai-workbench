"""Agent 工作模式白名单、重复调用提醒、空结果说明、最终回答数字校验、计划状态校验。纯离线。"""
import pytest

from agentfake import FakeLLM, call
from dzbench.agent.gateway import GatewayError
from dzbench.agent.loop import AgentLoop, MODES


def G(llm):
    lp = AgentLoop(llm, h())
    lp.guards = True
    return lp


def h(**kw):
    base = {"read_telemetry": lambda **a: {"ch": {"last": 1.5}}, "list_params": lambda **a: [],
            "propose_edit": lambda **a: "ok", "list_files": lambda **a: ["a.c"]}
    base.update(kw)
    return base


def tool_msgs(llm):
    return [m["content"] for m in llm.seen[-1][0] if m["role"] == "tool"]


def test_mode_narrows_tools_and_blocks_call():
    llm = FakeLLM([{"role": "assistant", "content": None, "tool_calls": [call("propose_edit", path="a.c", search="x", replace="y")]},
                   {"role": "assistant", "content": "只读模式下不能改"}])
    lp = AgentLoop(llm, h())
    lp.set_mode("diagnose")
    lp.ask("改一下")
    names = {t["name"] for t in llm.seen[0][1]}
    assert "propose_edit" not in names and "read_telemetry" in names
    assert "诊断" in tool_msgs(llm)[0] and "不能用 propose_edit" in tool_msgs(llm)[0]
    assert "诊断】模式" in llm.seen[0][0][-1]["content"]
    with pytest.raises(GatewayError):
        lp.set_mode("yolo")
    assert all(m["tools"] is None or "update_plan" in m["tools"] for m in MODES.values())


def test_repeat_reminder_and_empty_result():
    same = {"role": "assistant", "content": None, "tool_calls": [call("list_files")]}
    llm = FakeLLM([same, same, same, {"role": "assistant", "content": None, "tool_calls": [call("list_params")]},
                   {"role": "assistant", "content": "完"}])
    G(llm).ask("看看")
    t = tool_msgs(llm)
    assert "第 3 次" in t[2] and "第" not in t[1]
    assert "没有数据" in t[3]


def test_final_answer_must_cite_numbers_once():
    llm = FakeLLM([{"role": "assistant", "content": None, "tool_calls": [call("read_telemetry")]},
                   {"role": "assistant", "content": "看起来挺好"},
                   {"role": "assistant", "content": "还是挺好"}])
    out = G(llm).ask("怎么样")
    assert out == "还是挺好"                                # 只退回一次，不死循环
    assert "没有引用任何具体数字" in llm.seen[2][0][-1]["content"]
    llm2 = FakeLLM([{"role": "assistant", "content": None, "tool_calls": [call("read_telemetry")]},
                    {"role": "assistant", "content": "【实测】ch 最新 1.5"}])
    assert G(llm2).ask("怎么样") == "【实测】ch 最新 1.5" and len(llm2.seen) == 2


def test_note_reaches_model():
    llm = FakeLLM([{"role": "assistant", "content": "知道了"}])
    lp = AgentLoop(llm, h())
    lp.note("用户撤销了你的改动")
    lp.ask("继续")
    assert any("工作台通知" in m["content"] for m in llm.seen[0][0] if m["role"] == "user")


def test_guards_off_by_default():
    llm = FakeLLM([{"role": "assistant", "content": None, "tool_calls": [call("read_telemetry")]},
                   {"role": "assistant", "content": "挺好"}])
    assert AgentLoop(llm, h()).ask("怎么样") == "挺好"


def test_update_plan_status_rules():
    from types import SimpleNamespace
    from dzbench.agent.service import AgentService
    ev = []
    me = SimpleNamespace(emit=ev.append)
    up = lambda steps, **k: AgentService.update_plan(me, steps, **k)  # noqa: E731
    r = up([{"step": "看数据", "status": "completed"}, {"step": "改 kp", "status": "in_progress"}, {"step": "复测", "status": "pending"}])
    assert r == {"shown": 3, "done": 1} and ev[-1]["current"] == 1
    assert up(["a", "b"], current=1) and ev[-1]["items"][0]["status"] == "completed"   # 旧写法兼容
    for bad in ([{"step": "a", "status": "in_progress"}, {"step": "b", "status": "in_progress"}],
                [{"step": "a", "status": "pending"}, {"step": "a", "status": "pending"}],
                [{"step": "", "status": "pending"}], [{"step": "a", "status": "doing"}]):
        with pytest.raises(GatewayError):
            up(bad)
