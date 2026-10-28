"""link_schema.json：按心跳里的哈希自动匹配（零配置），并按字段表解码遥测。"""
from __future__ import annotations

import json
import os
import pathlib
import struct

from .transport import ROOT

FMT = {"f32": "f", "u32": "I", "i32": "i", "u16": "H", "i16": "h", "u8": "B"}


class Schema:
    def __init__(self, d: dict, path: str = ""):
        self.d, self.path = d, path
        self.hash = int(d["hash"])
        tel = d["telemetry"]
        self.telem_id = tel["id"]
        self.fields = tel["fields"]
        self._fmt = "<" + "".join(FMT[f["type"]] for f in self.fields)
        self.size = struct.calcsize(self._fmt)
        self.params = d.get("params", [])
        self.param_index = {p["name"]: i for i, p in enumerate(self.params)}

    @classmethod
    def load(cls, path) -> "Schema":
        return cls(json.loads(pathlib.Path(path).read_text(encoding="utf-8")), str(path))

    def decode(self, payload: bytes) -> dict | None:
        if len(payload) != self.size:
            return None
        return dict(zip((f["name"] for f in self.fields), struct.unpack(self._fmt, payload)))

    def clamp(self, name: str, v: float) -> tuple[float, bool]:
        p = self.params[self.param_index[name]]
        c = min(max(v, p["min"]), p["max"])
        if p["type"] != "f32":
            c = float(round(c))
        return c, c != v

    def summary(self) -> dict:
        return {"hash": f"{self.hash:08X}", "path": self.path, "fields": self.fields, "params": self.params,
                "period_ms": self.d["telemetry"].get("period_ms")}


def search_dirs() -> list[pathlib.Path]:
    extra = os.environ.get("DZBENCH_SCHEMA_DIRS", "")
    # 环境变量 → 仓库 build/（开发/源码运行）→ ~/.dzbench/schemas（打包版：把 link_schema.json 拷进去）
    from .snapshots import base_dir
    return [pathlib.Path(p) for p in extra.split(os.pathsep) if p] + [ROOT / "build", base_dir() / "schemas"]


def find_by_hash(h: int) -> Schema | None:
    for d in search_dirs():
        if not d.is_dir():
            continue
        for f in d.rglob("link_schema.json"):
            try:
                s = Schema.load(f)
            except (ValueError, KeyError, OSError):
                continue
            if s.hash == h:
                return s
    return None
