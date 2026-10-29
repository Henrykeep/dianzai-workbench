#!/usr/bin/env python3
"""检查 third_party/vendored/ 每个来源都有 LICENSE、SOURCE.md，代码文件都有 Source: 头。"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = re.compile(r"Source:\s*\S+@[0-9a-f]{7,40}\s+\S+")
CODE = {".py", ".c", ".h", ".ts", ".js"}


def check(base: pathlib.Path) -> list[str]:
    errs = []
    if not base.is_dir():
        return errs
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        names = {p.name for p in d.iterdir()}
        if not names & {"LICENSE", "COPYING", "LICENSE.txt"}:
            errs.append(f"{d.relative_to(ROOT)}: 缺 LICENSE")
        sm = d / "SOURCE.md"
        if not sm.is_file() or not SRC.search(sm.read_text(encoding="utf-8")):
            errs.append(f"{d.relative_to(ROOT)}: 缺 SOURCE.md 或其中没有 Source: repo@commit path")
        for f in d.rglob("*"):
            if f.suffix in CODE and "__pycache__" not in f.parts:
                head = "\n".join(f.read_text(encoding="utf-8").splitlines()[:15])
                if not SRC.search(head):
                    errs.append(f"{f.relative_to(ROOT)}: 前 15 行缺 Source: repo@commit path")
    ref = (ROOT / "docs/参考来源.md").read_text(encoding="utf-8")
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        if f"third_party/vendored/{d.name}" not in ref:
            errs.append(f"docs/参考来源.md 未登记 third_party/vendored/{d.name}")
    return errs


def main() -> int:
    errs = check(ROOT / "third_party" / "vendored")
    for e in errs:
        print("✗", e)
    print("check_vendored:", "失败" if errs else "通过")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
