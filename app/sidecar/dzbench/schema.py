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

    def check(self, name: str, raw) -> float:
        """#40：写参数前按参数表校验类型与范围；不合法直接拒绝（LinkError invalid_param），不钳位。"""
        return check_value(name, raw, self.params[self.param_index[name]] if name in self.param_index else None)

    def clamp(self, name: str, v: float) -> tuple[float, bool]:
        p = self.params[self.param_index[name]]
        c = min(max(v, p["min"]), p["max"])
        if p["type"] != "f32":
            c = float(round(c))
        return c, c != v

    def summary(self) -> dict:
        return {"hash": f"{self.hash:08X}", "path": self.path, "fields": self.fields, "params": self.params,
                "period_ms": self.d["telemetry"].get("period_ms"),
                # 只给界面：验收规格、串级分层（gen_link 从 yaml link: 段原样带过来；字段的 cal 在 fields 里）
                "accept": self.d.get("accept") or [], "loops": self.d.get("loops") or [],
                "protect_fixed": self.d.get("protect_fixed") or []}


def search_dirs() -> list[pathlib.Path]:
    extra = os.environ.get("DZBENCH_SCHEMA_DIRS", "")
    # 环境变量 → 仓库 build/（开发/源码运行）→ ~/.dzbench/schemas（打包版：把 link_schema.json 拷进去）
    from .snapshots import base_dir
    return [pathlib.Path(p) for p in extra.split(os.pathsep) if p] + ([pathlib.Path(os.environ["DZBENCH_REPO"]) / "build"] if os.environ.get("DZBENCH_REPO") else []) + [ROOT / "build", base_dir() / "schemas"]


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


def _invalid(name: str, why: str, p: dict | None):
    from .session import LinkError
    rng = f"{p['min']:g} ~ {p['max']:g}" if p and "min" in p and "max" in p else ""
    integral = bool(p) and p.get("type", "f32") != "f32"
    eg = (f"{int(p['min'])}" if integral else f"{(p['min'] + p['max']) / 2:g}") if rng else "0.5"
    msg = f"参数 {name} 的值不合法：{why}" + (f"（允许 {rng}{'，整数' if integral else ''}）" if rng else "")
    return LinkError("invalid_param", msg, f"填一个{'整数' if integral else '十进制数'}，例如 {eg}" + (f"，范围 {rng}" if rng else ""),
                     "params", {"message_zh": msg, "name": name, "reason": why, "example": eg})


def check_value(name: str, raw, p: dict | None = None) -> float:
    """把界面 / Agent 给的值转成数：只收十进制数（int/float 或数字字符串）。
    拒绝：None、空串、'abc'、'0x10'、'1,5'、布尔、NaN、±Inf、越界、整数参数给小数。"""
    import math
    if isinstance(raw, bool) or raw is None:
        raise _invalid(name, "不是数字", p)
    if isinstance(raw, (int, float)):
        v = float(raw)
    elif isinstance(raw, str):
        t = raw.strip()
        if not t or any(c in t for c in ",，xX_"):
            raise _invalid(name, "不是十进制数", p)
        try:
            v = float(t)
        except ValueError:
            raise _invalid(name, "不是十进制数", p) from None
    else:
        raise _invalid(name, "不是数字", p)
    if math.isnan(v) or math.isinf(v):
        raise _invalid(name, "NaN / 无穷大不能写入", p)
    if p:
        if p.get("type", "f32") != "f32" and v != round(v):
            raise _invalid(name, "这个参数只能是整数", p)
        if "min" in p and "max" in p and not p["min"] <= v <= p["max"]:
            raise _invalid(name, "超出范围", p)
    return v
