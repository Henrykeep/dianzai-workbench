#!/usr/bin/env python3
"""AGENTS.md / llms.txt / docs/README.md 同步检查（思路参考 SerialWeb 的 --check 同步脚本；代码自写）。

--check（默认）：
  1. docs/ 下每个 .md 都要出现在 docs/README.md 索引和 llms.txt 里；
  2. llms.txt 的 [..](路径) 链接和 AGENTS.md 里反引号包着的仓库路径都要存在；
  3. AGENTS.md 里出现的 `make <目标>` 要在 Makefile 里有。
--selftest：用临时目录验证上面三条能报错。
"""
from __future__ import annotations

import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATHLIKE = re.compile(r"`((?:docs|tools|firmware|ports|boards|apps|examples|host|app|third_party)/[^`*<>\s]*)`")


BOARD_MIX = [("天空星", re.compile(r"MSPM0|tianmengxing|G3507", re.I)),
             ("天猛星", re.compile(r"F407|STM32|skystar", re.I))]


def board_names(root: pathlib.Path) -> list[str]:
    """天空星 = STM32F407，天猛星 = MSPM0G3507。同一行写反了就报（“F407(天空星) / MSPM0G3507”这种并列除外：按逗号/斜杠分段看）。"""
    errs = []
    files = list(root.glob("*.md")) + list((root / "docs").glob("*.md")) + list(root.glob("boards/*/board.yaml")) + list(root.glob("ports/*/README.md"))
    for f in files:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if "board-names-ok" in line:
                continue
            for seg in re.split(r"[，,/、；;|（）()]", line):
                for name, bad in BOARD_MIX:
                    if name in seg and bad.search(seg):
                        errs.append(f"{f.relative_to(root)}:{i} 板名可能写反：{seg.strip()[:60]}（天空星=F407，天猛星=MSPM0）")
    return errs


def check(root: pathlib.Path) -> list[str]:
    errs = []
    agents, llms = root / "AGENTS.md", root / "llms.txt"
    for f in (agents, llms):
        if not f.exists():
            errs.append(f"缺少 {f.name}")
    if errs:
        return errs
    a, l = agents.read_text(encoding="utf-8"), llms.read_text(encoding="utf-8")
    idx = (root / "docs/README.md").read_text(encoding="utf-8")
    for d in sorted((root / "docs").glob("*.md")):
        if d.name == "README.md":
            continue
        if d.name not in idx:
            errs.append(f"docs/README.md 索引缺 {d.name}")
        if f"docs/{d.name}" not in l:
            errs.append(f"llms.txt 缺 docs/{d.name}")
    for link in re.findall(r"\]\(([^)]+)\)", l):
        if not link.startswith("http") and not (root / link).exists():
            errs.append(f"llms.txt 链接不存在：{link}")
    for p in PATHLIKE.findall(a):
        if not list(root.glob(p.rstrip("/"))):
            errs.append(f"AGENTS.md 提到的路径不存在：{p}")
    mk = (root / "Makefile").read_text(encoding="utf-8")
    for t in set(re.findall(r"`make ([a-z][\w-]*)", a)):
        if not re.search(rf"^{re.escape(t)}\s*:", mk, re.M):
            errs.append(f"AGENTS.md 提到 make {t}，Makefile 里没有")
    return errs + board_names(root)


def selftest() -> None:
    with tempfile.TemporaryDirectory() as t:
        r = pathlib.Path(t)
        (r / "docs").mkdir()
        (r / "docs/README.md").write_text("| 01-a.md |", encoding="utf-8")
        (r / "docs/01-a.md").write_text("x", encoding="utf-8")
        (r / "docs/02-b.md").write_text("天猛星 STM32F407 核心板\nF407(天空星) / MSPM0G3507 都行", encoding="utf-8")
        (r / "Makefile").write_text("check:\n", encoding="utf-8")
        (r / "AGENTS.md").write_text("`make check` `make nope` `tools/gone.py`", encoding="utf-8")
        (r / "llms.txt").write_text("[a](docs/01-a.md) [x](docs/zz.md)", encoding="utf-8")
        e = "\n".join(check(r))
        for want in ("索引缺 02-b.md", "llms.txt 缺 docs/02-b.md", "链接不存在：docs/zz.md", "tools/gone.py", "make nope", "02-b.md:1 板名可能写反"):
            assert want in e, (want, e)
        assert "make check" not in e and "02-b.md:2" not in e
    print("✓ check_ai_docs 自检")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    errs = check(ROOT)
    for x in errs:
        print("✗", x)
    if not errs:
        print("✓ AGENTS.md / llms.txt / docs 索引一致")
    sys.exit(1 if errs else 0)
