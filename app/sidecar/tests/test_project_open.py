"""project.open / project.list：打开已有项目、列出可选项目（RPC 与 Agent 工具同一接口）。"""
import asyncio
import datetime

import pytest

from dzbench import project, server as srv
from dzbench.session import LinkError


@pytest.fixture
def sv(home, monkeypatch):
    root = home / "repo"
    for c in ("demo", "2026X_follow"):
        (root / "examples" / c).mkdir(parents=True)
    (root / "examples" / "demo" / "requirements.yaml").write_text("items:\n  - {id: a, text: 速度误差}\n", encoding="utf-8")
    (root / "examples" / "notes.txt").write_text("x", encoding="utf-8")     # 文件不算项目
    s = srv.Server()
    monkeypatch.setattr(s.svc.gw, "root", root)
    s.progress._doctor = lambda: []
    sent = []

    async def bc(msg):
        sent.append(msg)
    s._broadcast = bc
    s.sent = sent
    return s


def op(s, **m):
    return asyncio.run(s._op(m))


def test_open_valid_sets_current_and_pushes_progress(sv):
    op(sv, op="progress.get")
    sv.progress.changed()                                   # 基线
    r = op(sv, op="project.open", code="demo")
    want = {"path": str(sv.svc.gw.root / "examples" / "demo"), "name": "demo"}
    assert r == {"project": want}
    assert op(sv, op="hello")["project"] == want
    pcs = [m for m in sv.sent if m.get("type") == "progress.changed"]
    assert pcs and pcs[-1]["project"] == want and pcs[-1]["steps"][0]["state"] == "done"


@pytest.mark.parametrize("code,err", [("../etc", "project_code_invalid"), ("a/b", "project_code_invalid"),
                                      ("a\\b", "project_code_invalid"), ("..", "project_code_invalid"),
                                      ("", "project_code_missing"), (None, "project_code_missing")])
def test_open_bad_code(sv, code, err):
    with pytest.raises(LinkError) as ei:
        op(sv, op="project.open", code=code)
    e = ei.value.as_dict()
    assert e["code"] == err and e["fix"] and e["fix_action"] == "project_list"
    assert project.current() is None


def test_open_missing_project(sv):
    with pytest.raises(LinkError) as ei:
        op(sv, op="project.open", code="nope")
    assert ei.value.code == "project_not_found" and "examples/nope" in ei.value.message
    assert ei.value.fix_action == "project_list"
    with pytest.raises(LinkError):
        op(sv, op="project.open", code="notes.txt")         # 文件不是项目目录


def test_open_persists_across_restart(sv, monkeypatch):
    op(sv, op="project.open", code="2026X_follow")
    assert project._path().exists()
    s2 = srv.Server()
    s2.progress._doctor = lambda: []
    assert op(s2, op="hello")["project"]["name"] == "2026X_follow"


def test_list(sv):
    import os
    old = sv.svc.gw.root / "examples" / "2026X_follow"
    os.utime(old, (1e9, 1e9))
    r = op(sv, op="project.list")
    assert sorted(p["code"] for p in r["projects"]) == ["2026X_follow", "demo"]
    for p in r["projects"]:
        assert set(p) == {"code", "name", "updated_at"}
        assert datetime.datetime.fromisoformat(p["updated_at"]).tzinfo is not None
    assert r["current"] is None
    assert r["projects"][0]["code"] == "demo"              # demo 里刚写过文件，最新


def test_agent_tools_same_interface(sv):
    from dzbench.agent import loop, risk
    names = {t["name"] for t in loop.TOOLS}
    assert {"project_list", "project_open"} <= names <= set(sv.svc.loop.handlers) | names
    assert {"project_list", "project_open"} <= loop._READ
    assert risk.RISK["project_list"] == risk.AUTO == risk.RISK["project_open"]
    assert sv.svc.project_list() == op(sv, op="project.list")
    assert sv.svc.project_open("demo")["project"]["name"] == "demo"
    bad = sv.svc.project_open("../x")
    assert bad["error"] == "project_code_invalid" and bad["fix_action"] == "project_list"
