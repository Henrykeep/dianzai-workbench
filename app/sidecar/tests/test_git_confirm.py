"""#88：写文件确认卡只授权写文件；git 提交必须另点提交确认卡。"""
import subprocess

import pytest

from dzbench.agent.gateway import Gateway
from test_agent import Runner, repo  # noqa: F401  复用真 git 仓库夹具


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
    cards = [e for e in ev if e.get("type") == "git_confirm"]
    assert [c["change_id"] for c in cards] == ids and all(c["status"] == "pending" and c["op"] == "commit" for c in cards)
    assert cards[0]["files"] == ["apps/x/f0.c"] and "新建" in cards[0]["message"]
    assert len([p for p in g.pending() if p["type"] == "git_confirm"]) == 4
    assert (repo / "apps/x/f3.c").read_text() == "int f3;\n"     # 文件已写入


def test_commit_only_after_approval_and_reject_returns_reason(repo):
    g = Gateway(repo, runner=Runner())
    before = _count(repo)
    a = g.propose_edit("apps/x/a.c", "", "a\n", "r")["id"]
    b = g.propose_edit("apps/x/b.c", "", "b\n", "r")["id"]
    g.decide(a, True); g.decide(b, True)
    r = g.commit_decide(b, False)
    assert r["ok"] is False and r["reason_zh"] and r["fix_action"] and _count(repo) == before
    r = g.commit_decide(a, True)
    assert r["ok"] is True and r["status"] == "committed" and _count(repo) == before + 1
    with pytest.raises(Exception):
        g.commit_decide(a, True)                               # 一张卡只能用一次


@pytest.mark.parametrize("op", ["commit", "branch", "reset", "push", "tag"])
def test_unapproved_git_mutation_refused(repo, op):
    g = Gateway(repo, runner=Runner())
    before = _count(repo)
    r = g.git_mutate(op, "-m", "x") if op == "commit" else g.git_mutate(op, "x")
    assert r == {"ok": False, "op": op, "reason_zh": r["reason_zh"], "fix_action": "propose_git_confirm"}
    assert _count(repo) == before
