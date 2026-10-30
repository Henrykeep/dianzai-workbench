"""视觉知识包（缺口第 6 项）：docs/agent-knowledge/vision-*.md 能按触发词加载，引用的仓库路径都存在，篇幅受控。"""
import pathlib
import re

from dzbench.agent import knowledge

ROOT = pathlib.Path(__file__).resolve().parents[3]


def _vision():
    return {k["name"]: k for k in knowledge.load(ROOT) if k["name"].startswith("vision-")}


def test_vision_pack_loads():
    assert set(_vision()) == {"vision-k230.md", "vision-color.md", "vision-tuning.md"}


def test_triggers_hit_typical_questions():
    items = knowledge.load(ROOT)
    for q, want in [("K230 上钢球识别怎么接主控", "vision-k230.md"),
                    ("红色激光点用 HSV 怎么设阈值", "vision-color.md"),
                    ("识别 FPS 只有 12，帧率低怎么办", "vision-tuning.md")]:
        names = [k["name"] for k in knowledge.match(q, items, set())]
        assert want in names, (q, names)
    assert not [k for k in knowledge.match("左轮速度环 kp 调多少", items, set()) if k["name"].startswith("vision-")]


def test_paths_exist_and_short():
    for k in _vision().values():
        assert len(k["body"]) < 1200, k["name"]          # 字符数；进对话前缀，不能太长
        for p in re.findall(r"`((?:third_party|host|boards|tools|docs|firmware)/[^`\s]+)`", k["body"]):
            assert (ROOT / p).exists(), (k["name"], p)
