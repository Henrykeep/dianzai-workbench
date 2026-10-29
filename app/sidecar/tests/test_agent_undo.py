"""计划卡、板子记忆、一键撤销（参数 + git 提交）——在仿真板上走一遍。"""
import time

from agentfake import FakeLLM, call
from dzbench.agent.service import AgentService
from dzbench.agent_api import AgentTools
from dzbench.session import Session
from test_agent import Runner, repo  # noqa: F401  —— 复用 fixture


def wait(pred, t=10):
    t0 = time.monotonic()
    while time.monotonic() - t0 < t:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_plan_memory_and_undo(home, repo):  # noqa: F811
    s = Session()
    s.connect("sim:car_2wd")
    try:
        assert wait(lambda: s.schema and len(s.params) == len(s.schema.params))
        name = s.schema.params[0]["name"]
        old = s.params[name]

        ev = []
        tools = AgentTools(s, ev.append)
        new = old * 0.9 if old else 0.01
        llm = FakeLLM([
            {"role": "assistant", "content": None, "tool_calls": [
                call("update_plan", steps=["看数据", "改一个参数", "复测"], current=1),
                call("propose_param_change", name=name, value=new, reason="t"),
                call("propose_edit", path="apps/x/main.c", search="int gain = 1;", replace="int gain = 2;", reason="t")]},
            {"role": "assistant", "content": "好"}])
        svc = AgentService(s, tools, ev.append, root=repo, llm=llm, runner=Runner())
        svc.ask("调一下")
        assert any(e.get("type") == "agent_plan" and e["current"] == 1 and len(e["steps"]) == 3 for e in ev)
        pid = next(e["id"] for e in ev if e.get("type") == "proposal")
        tools.decide(pid, True)
        cid = next(e["id"] for e in ev if e.get("type") == "change")
        assert svc.gw.decide(cid, True)["status"] == "committed"
        assert [j["kind"] for j in svc.journal_list()] == ["param", "commit"]
        assert {r["kind"] for r in svc.memory().load()} >= {"param", "commit"}
        # 倒序撤销：先 git，再参数
        assert svc.undo_last()["undone"] == "commit"
        assert (repo / "apps/x/main.c").read_text().startswith("int gain = 1;")
        r = svc.undo_last()
        assert r["undone"] == "param" and abs(s.params[name] - old) < 1e-6
        assert svc.journal_list() == []
        # 记忆跨会话：新服务读得到
        svc2 = AgentService(s, AgentTools(s, ev.append), ev.append, root=repo, llm=FakeLLM([]), runner=Runner())
        assert svc2.memory().summary()["entries"] >= 3
    finally:
        s.disconnect()
