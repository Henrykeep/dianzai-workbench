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
    from dzbench import paths
    assert not paths.projects_dir().exists() or not any(paths.projects_dir().iterdir())
    assert steptools.fresh_code(ROOT, "2026H_ball") == "2026h-ball"               # r9q (c)：干净 HOME 第一个就是 2026h-ball，例题不算占用
    (paths.projects_dir() / "2026h-ball").mkdir(parents=True)
    assert steptools.fresh_code(ROOT, "2026H_ball") == "2026h-ball-2"             # 只有真实项目才算重名
    (paths.projects_dir() / "2026H-Ball-2").mkdir(parents=True)
    assert steptools.fresh_code(ROOT, "2026H_ball") == "2026h-ball-3"             # 不分大小写（Windows）
    (paths.projects_dir() / "qabc123").mkdir(parents=True)
    assert steptools.fresh_code(ROOT, "Qabc123") == "qabc123-2"
    assert steptools.fresh_code(ROOT, "Qnew999") == "qnew999"


def test_chinese_name_gives_ascii_dir(tmp_path):
    """#55：项目名是中文也落 ASCII 目录（如 2026h-ball-3 / proj-xxxxxx）；中文显示名存 project.yaml 的 display_name。"""
    import yaml
    from dzbench import paths
    for name in ("平衡滚球", "2026年H题 平衡滚球", "２０２６Ｈ　滚球"):
        c = steptools.fresh_code(ROOT, name)
        assert c.isascii() and c == c.lower() and all(ch.isalnum() or ch == "-" for ch in c), c
        d = paths.projects_dir() / c
        d.mkdir(parents=True)
        steptools.set_display_name(d, name)
        assert str(d.relative_to(paths.projects_dir())).isascii()
        y = yaml.safe_load((d / "project.yaml").read_text(encoding="utf-8"))
        assert y["display_name"] == name and y["name"] == c
        assert steptools.fresh_code(ROOT, name) != c                            # 再建同名 → 新目录
    assert steptools.fresh_code(ROOT, "２０２６Ｈ　滚球").startswith("2026h")


def test_chain_refuses_example_as_new_project():
    ex = next(d.name for d in (ROOT / "examples").iterdir() if d.is_dir())
    with pytest.raises(FlowError) as e:
        steptools.project_chain(ROOT, ex)
    assert e.value.code == "example_readonly"


def test_slug_pinyin_fullwidth_and_collision():
    """#55：中文 → 无声调拼音（pypinyin）；全角 → ASCII；重名加 -2/-3；转完为空才 proj-<哈希>。"""
    from dzbench import paths
    assert steptools.slug("2026H小球") == "2026h-xiaoqiu"
    assert steptools.slug("平衡滚球") == "pinghenggunqiu"
    assert steptools.slug("２０２６Ｈ　小球") == "2026h-xiaoqiu"          # 全角数字/字母/空格
    assert steptools.slug("ＰＩＤ＿电机") == "pid-dianji"
    assert steptools.slug("！！？").startswith("proj-")
    assert steptools.fresh_code(ROOT, "2026H小球") == "2026h-xiaoqiu"
    (paths.projects_dir() / "2026h-xiaoqiu").mkdir(parents=True)
    assert steptools.fresh_code(ROOT, "2026H小球") == "2026h-xiaoqiu-2"
    (paths.projects_dir() / "2026h-xiaoqiu-2").mkdir(parents=True)
    assert steptools.fresh_code(ROOT, "２０２６Ｈ小球") == "2026h-xiaoqiu-3"


def test_slug_contest_phrases():
    """电赛常用词按词读音（pypinyin load_phrases_dict 短词表）：调参不是 diaocan。"""
    assert steptools.slug("调参") == "tiaocan"
    assert steptools.slug("2026H调试") == "2026h-tiaoshi"
    assert steptools.slug("重心") == "zhongxin"
    assert steptools.slug("电调") == "diantiao"
    assert steptools.slug("2026H小球") == "2026h-xiaoqiu"          # 不在短词表里的照旧
