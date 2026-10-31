"""#39：板子记忆 / 调参历史按项目目录隔离；新建项目一律落新目录，不复用示例或旧项目的初值。"""
from __future__ import annotations

import pathlib

import pytest

from dzbench.agent import steptools
from dzbench.agent.journal import BoardMemory, project_slug
from dzbench.projflow import FlowError

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_memory_isolated_per_project_dir(tmp_path):
    a, b = tmp_path / "projects" / "A", tmp_path / "other" / "A"     # 同名不同目录也分开
    m1 = BoardMemory("1234abcd", str(a))
    m1.add("param", name="kp", old=0.0, new=0.72, note="第一次运行的初值")
    assert m1.summary()["entries"] == 1
    m2 = BoardMemory("1234abcd", str(b))
    assert m2.summary()["entries"] == 0 and m2.load() == []          # 第二次运行看不到第一次的初值
    assert BoardMemory("1234abcd", None).load() == []
    assert project_slug(str(a)) != project_slug(str(b))
    assert BoardMemory("1234abcd", str(a)).load()[0]["new"] == 0.72  # 同一项目跨会话仍记得


def test_fresh_code_never_reuses(tmp_path):
    ex = next(d.name for d in (ROOT / "examples").iterdir() if d.is_dir())
    assert steptools.fresh_code(ROOT, ex) == ex + "-2"
    from dzbench import paths
    (paths.projects_dir() / "Qabc123").mkdir(parents=True)
    assert steptools.fresh_code(ROOT, "Qabc123") == "Qabc123-2"
    assert steptools.fresh_code(ROOT, "Qnew999") == "Qnew999"


def test_chain_refuses_example_as_new_project():
    ex = next(d.name for d in (ROOT / "examples").iterdir() if d.is_dir())
    with pytest.raises(FlowError) as e:
        steptools.project_chain(ROOT, ex)
    assert e.value.code == "example_readonly"
