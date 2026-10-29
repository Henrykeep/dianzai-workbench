"""Agent 改动日志 + 板子记忆。

思路来源（只借思路，代码自写）：
- Aider（Apache-2.0）：每次改动一个 git 提交、/undo 撤销最近一次；
- Cline（Apache-2.0）：每步留 checkpoint，可一键回到之前；
- Claude Code 公开文档：会话间记住项目事实（CLAUDE.md / memory）。

Journal：本次会话里 Agent 造成、且已被人确认落地的改动（参数 / git 提交），按时间倒序撤销。
BoardMemory：按“数据格式哈希 + 芯片 ID”存到 ~/.dzbench/memory/，跨会话记住这块板的参数变化和实验结论。
"""
from __future__ import annotations

import json
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


class BoardMemory:
    def __init__(self, key: str | None):
        self.key = key
        self.path = snapshots.base_dir() / "memory" / f"{key}.json" if key else None

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
        return {"board": self.key, "entries": len(rows), "recent": rows[-n:]}
