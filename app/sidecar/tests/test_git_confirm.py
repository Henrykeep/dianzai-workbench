"""#88：写文件确认卡只授权写文件；git 提交必须另点提交确认卡。"""
import subprocess

import pytest

from dzbench.agent.gateway import Gateway
import test_agent
from test_agent import Runner

repo = test_agent.repo   # 复用真 git 仓库夹具


def _count(r):
    return int(subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=r, capture_output=True, text=True).stdout)


def test_regression_four_write_cards_make_no_silent_commits(repo):
    """r9b 复现：连点 4 张写文件卡，以前直接出 4 个 git 提交；现在 0 个，出 4 张待批的提交确认卡。"""
    ev = []
    g = Gateway(repo, ev.append, runner=Runner())
    before = _count(repo)
    ids = [g.propose_edit(f"apps/x/f{i}.c", "", f"int f{i};\n", "新建")["id"] for i in range(4)]
    for i in ids:
        assert g.decide(i, True)["status"] == "written"
    assert _count(repo) == before
    cards = [e for e in ev if e.get("type") == "commit_confirm_request"]
    assert [c["request_id"] for c in cards] == ids and all(c["status"] == "pending" and c["branch"] for c in cards)
    assert cards[0]["files"] == [{"path": "apps/x/f0.c", "status": "A"}] and "新建" in cards[0]["message"] and cards[0]["message_zh"]
    assert all(e["scope"] == "write_only" for e in ev if e.get("type") == "change")
    assert len([p for p in g.pending() if p["type"] == "commit_confirm_request"]) == 4
    assert (repo / "apps/x/f3.c").read_text() == "int f3;\n"     # 文件已写入


def test_commit_only_after_approval_and_reject_returns_reason(repo):
    g = Gateway(repo, runner=Runner())
    before = _count(repo)
    a = g.propose_edit("apps/x/a.c", "", "a\n", "r")["id"]
    b = g.propose_edit("apps/x/b.c", "", "b\n", "r")["id"]
    g.decide(a, True); g.decide(b, True)
    r = g.commit_decide(b, False)
    assert r["ok"] is False and r["reason"] == "commit_declined" and r["reason_zh"] and r["fix_action"] == "ask_user_commit"
    assert _count(repo) == before
    r = g.commit_decide(a, True)
    assert r["ok"] is True and r["status"] == "committed" and _count(repo) == before + 1
    with pytest.raises(Exception):
        g.commit_decide(a, True)                               # 一张卡只能用一次


@pytest.mark.parametrize("op", ["commit", "branch", "reset", "push", "tag"])
def test_unapproved_git_mutation_refused(repo  # noqa: F811
, op):
    g = Gateway(repo, runner=Runner())
    before = _count(repo)
    r = g.git_mutate(op, "-m", "x") if op == "commit" else g.git_mutate(op, "x")
    assert r == {"ok": False, "op": op, "reason_zh": r["reason_zh"], "reason": "commit_declined", "fix_action": "ask_user_commit"}
    assert _count(repo) == before


def test_timeout_counts_as_decline(repo):
    g = Gateway(repo, runner=Runner())
    before = _count(repo)
    a = g.propose_edit("apps/x/t.c", "", "t\n", "r")["id"]
    g.decide(a, True)
    r = g.commit_timeout(a)
    assert r["ok"] is False and r["reason"] == "commit_declined" and _count(repo) == before
