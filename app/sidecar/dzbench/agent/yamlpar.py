"""参数写回 yaml：只改 `- { name: X, ... default: V ... }` 这一行里的 default 值，其余字节不动（保留注释/对齐）。"""
from __future__ import annotations

import pathlib
import re

ROW = re.compile(r"^(\s*-\s*\{[^}]*\bname:\s*)(?P<name>[A-Za-z_]\w*)(?P<rest>[^}]*\})")
DEF = re.compile(r"(\bdefault:\s*)(-?[\d.eE+]+|[A-Za-z_]\w*)")


def fmt_num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() and abs(v) < 1e15 else f"{v:.6g}"


def rewrite(text: str, values: dict[str, float]) -> tuple[str, list[str]]:
    """返回 (新文本, 未找到的参数名)。"""
    found, out = set(), []
    for line in text.splitlines(keepends=True):
        m = ROW.match(line)
        if m and m["name"] in values:
            new, k = DEF.subn(lambda d: d.group(1) + fmt_num(values[m["name"]]), line, count=1)
            if k:
                found.add(m["name"])
                line = new
        out.append(line)
    return "".join(out), sorted(set(values) - found)


def param_files(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted([*root.glob("apps/*/app.yaml"), *root.glob("examples/*/project.yaml")])
