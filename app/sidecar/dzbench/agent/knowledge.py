"""按触发词加载的知识 + 人确认后才更新的项目记忆。

- 知识：`docs/agent-knowledge/*.md`，文件头 `---\ntriggers: 堵转, stall\n---`。用户这句话里出现任一触发词时，
  把这篇的正文附在这句话前面（一次对话里每篇只附一次）。思路参考 OpenHands 的 knowledge microagents（MIT）、
  Claude Code skills 的按需加载；代码自写。
- 项目记忆：`docs/agent-knowledge/project-memory.md`，每次新对话放进系统提示。Agent 只能用 remember 工具**提议**追加一条，
  走网关的 diff 卡片，人点“接受”才写入并提交（与改代码同一条路，不另开后门）。
"""
from __future__ import annotations

import pathlib
import re
import time

DIR = "docs/agent-knowledge"
MEMORY = f"{DIR}/project-memory.md"
MEMORY_MAX = 3000
_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def load(root: pathlib.Path) -> list[dict]:
    out = []
    for p in sorted((pathlib.Path(root) / DIR).glob("*.md")):
        if p.name == pathlib.Path(MEMORY).name:
            continue
        text = p.read_text(encoding="utf-8")
        m = _FM.match(text)
        if not m:
            continue
        trig = []
        for ln in m.group(1).splitlines():
            if ln.strip().startswith("triggers:"):
                trig = [x.strip().lower() for x in ln.split(":", 1)[1].split(",") if x.strip()]
        if trig:
            out.append({"name": p.name, "triggers": trig, "body": text[m.end():].strip()})
    return out


def match(text: str, items: list[dict], seen: set[str]) -> list[dict]:
    low = text.lower()
    hit = [k for k in items if k["name"] not in seen and any(t in low for t in k["triggers"])]
    seen.update(k["name"] for k in hit)
    return hit


def memory_text(root: pathlib.Path) -> str:
    p = pathlib.Path(root) / MEMORY
    if not p.exists():
        return ""
    t = p.read_text(encoding="utf-8").strip()
    return t[-MEMORY_MAX:]                        # 太长只留最新的


def propose_memory(gw, note: str, reason: str) -> dict:
    """提议往项目记忆追加一条（网关出 diff 卡，人接受后才写入）。"""
    note = " ".join(str(note).split())[:300]
    if len(note) < 6:
        from .gateway import GatewayError
        raise GatewayError("bad_memory", "记忆内容太短", "写一句完整的事实，例如“左电机编码器方向反，已在 board.yaml 里取反”")
    rel = gw.rel(MEMORY)
    gw.check(rel, "write")
    p = gw.root / rel
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    head = old or "# 项目记忆\n\n由内置 Agent 提议、人工接受后追加。每条一行，带日期（Asia/Shanghai）。错了直接删行。\n"
    new = head.rstrip("\n") + f"\n- {time.strftime('%Y-%m-%d')} {note}\n"
    return gw._propose(f"记住：{note[:30]}", reason, "agent", {rel: (old, new)}).card()
