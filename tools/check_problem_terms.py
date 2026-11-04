#!/usr/bin/env python3
"""防硬编码门：读题/生成工程/接线这几条代码路径里不许出现任何赛题的题名或题号。
词表从题库自动抽（--extract refs/problem-bank.md → tools/problem_terms.txt，提交进库），
检查时只读词表，所以 CI 不需要题库。题名短于 MIN_LEN 个字的不收（太泛会误报）。
SPDX-License-Identifier: AGPL-3.0-or-later"""
import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TERMS = ROOT / "tools/problem_terms.txt"
MIN_LEN = 4
PATHS = [
    "tools/req.py", "tools/scheme.py", "tools/alloc.py", "tools/gen_project.py", "tools/gen_link.py",
    "tools/add_subsys.py", "tools/gen_ioc.py", "tools/gen_core.py",
    "app/sidecar/dzbench/project.py", "app/sidecar/dzbench/projflow.py", "app/sidecar/dzbench/mcp_server.py",
    "app/sidecar/dzbench/cubemx.py", "app/sidecar/dzbench/agent/steptools.py",
    "tools/mcp/mkconfig.py", "tools/mcp/hwtools_launch.py",
]
ROW = re.compile(r"^\|\s*(\d{4})\s*\|\s*([A-Z])\s+([^|✅（(]+)")


def extract(bank: str) -> list[str]:
    terms = set()
    for line in pathlib.Path(bank).read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if not m:
            continue
        year, letter, title = m.group(1), m.group(2), m.group(3).strip()
        terms.add(f"{year}{letter}")
        terms.add(f"{year}年{letter}题")
        if len(title) >= MIN_LEN:
            terms.add(title)
    return sorted(terms)


def code_pattern(term: str) -> re.Pattern:
    if re.fullmatch(r"\d{4}[A-Z]", term):  # 年份+字母，允许中间有 - _ 空格，前后不能接字母数字
        return re.compile(rf"(?<![0-9A-Za-z]){term[:4]}[-_ ]?{term[4]}(?![0-9A-Za-z])", re.I)
    return re.compile(re.escape(term))


def scan(terms, files):
    pats = [(t, code_pattern(t)) for t in terms]
    hits = []
    for f in files:
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for t, p in pats:
                if p.search(line):
                    hits.append(f"{f.relative_to(ROOT) if f.is_relative_to(ROOT) else f}:{n}: 出现赛题词「{t}」")
    return hits


def selftest():
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp())
    yr, code = "20" + "99", "20" + "99" + "Z"  # 拼出来，免得本文件自己撞上 check_problem_specific
    (d / "bank.md").write_text(f"| {yr} | Z 测试用虚构题目 ✅已核对 | x |\n| 2098 | Y 短 ✅已核对 | x |\n", encoding="utf-8")
    t = extract(d / "bank.md")
    assert code in t and "测试用虚构题目" in t and "短" not in t, t
    (d / "bad.py").write_text(f"x = '{yr}-Z'\ny = '测试用虚构题目'\nz = 'v1{code}q'\n", encoding="utf-8")
    assert len(scan(t, [d / "bad.py"])) == 2
    (d / "ok.py").write_text(f"freq = {yr}\n", encoding="utf-8")
    assert not scan(t, [d / "ok.py"])
    print("check_problem_terms selftest ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", metavar="BANK")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.extract:
        t = extract(a.extract)
        TERMS.write_text("# 由 tools/check_problem_terms.py --extract 从题库自动生成，勿手改\n" + "\n".join(t) + "\n", encoding="utf-8")
        print(f"写入 {len(t)} 个词 → {TERMS.relative_to(ROOT)}")
        return
    if not TERMS.exists():
        sys.exit("✗ 缺 tools/problem_terms.txt（先跑 --extract）")
    terms = [x for x in TERMS.read_text(encoding="utf-8").splitlines() if x and not x.startswith("#")]
    files = [ROOT / p for p in PATHS if (ROOT / p).exists()]
    hits = scan(terms, files)
    for h in hits:
        print("✗", h)
    if hits:
        sys.exit(1)
    print(f"✓ 题名/题号门：{len(terms)} 个词 × {len(files)} 个文件，无命中")


if __name__ == "__main__":
    main()
