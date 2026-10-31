"""Agent 改动日志 + 板子记忆。

思路来源（只借思路，代码自写）：
- Aider（Apache-2.0）：每次改动一个 git 提交、/undo 撤销最近一次；
- Cline（Apache-2.0）：每步留 checkpoint，可一键回到之前；
- Claude Code 公开文档：会话间记住项目事实（CLAUDE.md / memory）。

Journal：本次会话里 Agent 造成、且已被人确认落地的改动（参数 / git 提交），按时间倒序撤销。
BoardMemory：按“项目目录 + 数据格式哈希 + 芯片 ID”存到 ~/.dzbench/memory/<项目>/，跨会话记住这块板在这个项目里的
参数变化和实验结论。不同项目（不同目录）互不可见：新项目从空记忆起步，不继承别的项目/示例的初值和结论（#39）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import threading
import time

from .. import snapshots

MAX_MEM = 200


class Journal:
    def __init__(self):
        self.items: list[dict] = []
        self.lock = threading.Lock()

    def add(self, kind: str, **kw) -> dict:
        e = {"kind": kind, "t": time.time(), **kw}
        with self.lock:
            self.items.append(e)
        return e

    def last(self) -> dict | None:
        with self.lock:
            return self.items[-1] if self.items else None

    def pop(self) -> dict | None:
        with self.lock:
            return self.items.pop() if self.items else None

    def push_back(self, e: dict) -> None:
        with self.lock:
            self.items.append(e)

    def list(self) -> list[dict]:
        with self.lock:
            return list(self.items)


def board_key(schema_hash: int | None, uid: int | None) -> str | None:
    if not schema_hash:
        return None
    return f"{schema_hash:08x}" + (f"-{uid:08x}" if uid else "")


def project_slug(project_path: str | None) -> str:
    """项目目录 → 记忆子目录名（名字 + 绝对路径哈希：同名不同目录也分开）；没打开项目 = _none。"""
    if not project_path:
        return "_none"
    p = pathlib.Path(project_path).expanduser().resolve()
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in p.name)[:40] or "p"
    return f"{safe}-{hashlib.sha1(str(p).encode()).hexdigest()[:10]}"


class BoardMemory:
    def __init__(self, key: str | None, project_path: str | None = None):
        self.key = key
        self.project = project_slug(project_path)
        self.path = snapshots.base_dir() / "memory" / self.project / f"{key}.json" if key else None

    def load(self) -> list[dict]:
        if not self.path or not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def add(self, kind: str, **kw) -> None:
        if not self.path:
            return
        rows = self.load()
        rows.append({"kind": kind, "t": time.strftime("%Y-%m-%d %H:%M"), **kw})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows[-MAX_MEM:], ensure_ascii=False, indent=0), encoding="utf-8")
        tmp.replace(self.path)

    def summary(self, n: int = 12) -> dict:
        rows = self.load()
        return {"board": self.key, "project": self.project, "entries": len(rows), "recent": rows[-n:]}
