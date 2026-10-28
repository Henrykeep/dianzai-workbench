"""key=value 文本遥测 → 虚拟 schema：视觉板 printf("x=%d,y=%d\\n")、第三方模块也能直接画曲线。
识别 `名字=数` 或 `名字:数`（逗号/空格/分号分隔都行），每行一个样本；新出现的名字自动加通道（最多 16 路）。
思路参考 SerialWeb 的文本模板解析；代码自写。
"""
from __future__ import annotations

import re

KV = re.compile(r"([A-Za-z_][A-Za-z0-9_]{0,23})\s*[=:]\s*(-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")
MAX_FIELDS = 16
VIRTUAL_HASH = 0


class KvParser:
    def __init__(self):
        self.buf = b""
        self.names: list[str] = []

    def feed(self, data: bytes) -> tuple[list[dict], bool]:
        """返回 (样本列表, 通道表是否变了)。"""
        self.buf += data
        if len(self.buf) > 4096 and b"\n" not in self.buf:
            self.buf = self.buf[-512:]                        # 不是文本流：别无限攒
        *lines, self.buf = self.buf.split(b"\n")
        out, grew = [], False
        for ln in lines:
            kv = KV.findall(ln.decode("utf-8", "replace"))
            if not kv:
                continue
            v = {}
            for k, x in kv:
                if k not in self.names:
                    if len(self.names) >= MAX_FIELDS:
                        continue
                    self.names.append(k)
                    grew = True
                v[k] = float(x)
            if v:
                out.append(v)
        return out, grew

    def schema_dict(self, period_ms: int | None = None) -> dict:
        return {"version": 1, "hash": VIRTUAL_HASH, "virtual": True,
                "telemetry": {"id": -1, "period_ms": period_ms, "fields": [{"name": n, "type": "f32"} for n in self.names]},
                "params": []}
