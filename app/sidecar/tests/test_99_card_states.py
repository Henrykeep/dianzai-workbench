"""#99：Agent 描述改代码卡状态要以真实状态为准（写入卡 + 提交卡），make check 不自动提交。"""
from types import SimpleNamespace

from dzbench.agent import loop as L
from dzbench.agent import service as S
from dzbench.agent.gateway import Gateway
import test_agent
from test_agent import Runner

repo = test_agent.repo


def test_agent_context_reflects_real_card_states(repo):
    g = Gateway(repo, runner=Runner())
    a = g.propose_edit("apps/x/a.c", "", "a\n", "r")["id"]
    b = g.propose_edit("apps/x/b.c", "", "b\n", "r")["id"]
    c = g.propose_edit("apps/x/c.c", "", "c\n", "r")["id"]
    g.decide(a, True); g.decide(b, True)
    g.commit_decide(b, False)
    g.commit_decide(a, True)
    st = {r["id"]: r for r in g.change_states()}
    assert st[a]["commit_status"] == "committed" and st[a]["commit"]
    assert st[b]["write_status"] == "written" and st[b]["commit_status"] == "rejected"
    assert st[c]["write_status"] == "pending" and st[c]["commit_status"] == ""
    ctx = S.AgentService._card_states(SimpleNamespace(gw=g))
    assert "已提交" in ctx.splitlines()[1] and "已写入（未提交）" in ctx and "用户拒绝提交" in ctx and "待确认写入" in ctx


def test_propose_edit_description_is_write_only_and_status_tool_readonly():
    d = next(t for t in L.TOOLS if t["name"] == "propose_edit")["description"]
    assert "自动 git 提交" not in d.replace("不会自动 git 提交", "") and "提交卡" in d
    assert "change_status" in L._READ and any(t["name"] == "change_status" for t in L.TOOLS)
    assert "change_status" in L.SYSTEM


def test_empty_card_states_adds_nothing():
    assert S.AgentService._card_states(SimpleNamespace(gw=SimpleNamespace(change_states=lambda: []))) == ""
