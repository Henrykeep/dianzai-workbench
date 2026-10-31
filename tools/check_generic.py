#!/usr/bin/env python3
"""通用性门禁（make check）：核心代码里不许出现针对某道题/某个例子的分支或名字。

工作台要能做任何题目、任何项目；examples/、apps/ 只是演示，不是门禁，核心代码不能认得它们。
回路数、阶跃通道、单位只能来自声明（app.yaml / project.yaml link:），不能按题号/应用名写死。

扫描（只看代码，不看注释和 Python 文档字符串）：
  失败：firmware/**/*.{c,h}、tools/**/*.{py,sh}（tools/test_*、fixtures、testdata 除外）
  只报告（--strict-sidecar 时也失败）：app/sidecar/dzbench/**/*.py —— 归后端，清单交给后端改
允许：firmware/algo/ball_beam/（通用的“球杆”被控对象算法库，按需引用，不是某道题）
用法：check_generic.py [--strict-sidecar] [--selftest]
"""
from __future__ import annotations

import io
import pathlib
import re
import sys
import tokenize

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAT = re.compile(r"2026[A-Z]|ball|xiaoqiu|小球|钢珠|motor_pos|pendulum|line_car|car_2wd|pan_tilt", re.I)
ALLOW = ("firmware/algo/ball_beam/", "tools/check_generic.py", "tools/check_ui_generic.py", "tools/check_problem_specific.py")   # 检查器自身的关键词表
CORE = [("firmware", ("*.c", "*.h")), ("tools", ("*.py", "*.sh"))]
SIDECAR = [("app/sidecar/dzbench", ("*.py",))]
SKIP = re.compile(r"(^|/)(test_[^/]*|fixtures/|testdata/|tests/)")


def c_code(text: str):
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    for i, ln in enumerate(text.splitlines(), 1):
        yield i, ln.split("//")[0]


def sh_code(text: str):
    for i, ln in enumerate(text.splitlines(), 1):
        yield i, re.sub(r"(^|\s)#.*$", "", ln)


def py_code(text: str):
    """NAME/STRING/OP 记号（去掉注释、文档字符串）。"""
    out: dict[int, str] = {}
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError):
        return list(enumerate(text.splitlines(), 1))
    prev = tokenize.NEWLINE
    for t in toks:
        if t.type == tokenize.COMMENT:
            continue
        if t.type == tokenize.STRING and prev in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.NL):
            prev = t.type
            continue                                   # 文档字符串 / 独立字符串语句
        if t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            out[t.start[0]] = out.get(t.start[0], "") + " " + t.string
        if t.type not in (tokenize.NL,):
            prev = t.type
    return sorted(out.items())


def scan(groups) -> list[str]:
    hits = []
    for base, globs in groups:
        for g in globs:
            for p in sorted((ROOT / base).rglob(g)):
                rel = p.relative_to(ROOT).as_posix()
                if rel.startswith(ALLOW) or SKIP.search(rel) or "/node_modules/" in rel:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
                lines = py_code(text) if p.suffix == ".py" else sh_code(text) if p.suffix == ".sh" else c_code(text)
                for n, code in lines:
                    m = PAT.search(code)
                    if m:
                        hits.append(f"{rel}:{n}: {m.group(0)}")
    return hits


def selftest() -> int:
    bad = list(py_code('x = 1\nif app == "2026H_ball":\n    pass\n'))
    good = list(py_code('"""2026H docstring"""\n# ball\nx = 1\n'))
    ok = any(PAT.search(c) for _, c in bad) and not any(PAT.search(c) for _, c in good)
    ok &= not any(PAT.search(c) for _, c in c_code("int a; /* ball */\n// 2026H\n")) and any(PAT.search(c) for _, c in c_code("int ball;\n"))
    print("✓ check_generic 自检" if ok else "✗ check_generic 自检：识别规则坏了")
    return 0 if ok else 1


def main(argv) -> int:
    if "--selftest" in argv:
        return selftest()
    core, side = scan(CORE), scan(SIDECAR)
    for h in side:
        print(f"  [sidecar，归后端] {h}")
    for h in core:
        print(f"✗ [通用性] {h}")
    fail = bool(core) or ("--strict-sidecar" in argv and bool(side))
    print(f"{'✗' if fail else '✓'} 通用性检查：核心 {len(core)} 处，sidecar {len(side)} 处{'（只报告）' if '--strict-sidecar' not in argv else ''}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
