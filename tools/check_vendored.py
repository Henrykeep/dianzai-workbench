#!/usr/bin/env python3
"""检查 third_party/vendored/ 每个来源都有 LICENSE、SOURCE.md，代码文件都有 Source: 头；
许可扫描：LICENSE 必须是可识别的宽松许可（MIT/BSD/Apache-2.0/zlib/ISC），出现 GPL/LGPL/AGPL（含 SPDX 标识、
LICENSE/SOURCE.md/代码文件头任何一处）或认不出许可即失败。自测：tools/test_check_vendored.py。"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = re.compile(r"Source:\s*\S+@[0-9a-f]{7,40}\s+\S+")
CODE = {".py", ".c", ".h", ".ts", ".js"}
COPYLEFT = re.compile(r"GNU\s+(AFFERO\s+|LESSER\s+|LIBRARY\s+)?GENERAL\s+PUBLIC\s+LICENSE|\b(A|L)?GPL(v?\d)?\b|SPDX-License-Identifier:\s*\S*GPL", re.I)
PERMISSIVE = {
    "MIT": re.compile(r"Permission is hereby granted, free of charge", re.I),
    "BSD": re.compile(r"Redistribution and use in source and binary forms", re.I),
    "Apache-2.0": re.compile(r"Apache License,?\s+Version 2\.0", re.I),
    "zlib": re.compile(r"This software is provided 'as-is'.*?altered source versions must be plainly marked", re.I | re.S),
    "ISC": re.compile(r"Permission to use, copy, modify, and(/or)? distribute this software for any purpose", re.I),
}


def classify(text: str) -> str:
    """'copyleft' / 许可名 / 'unknown'。copyleft 优先（双许可里带 GPL 也算失败，要人工确认后另行处理）。"""
    if COPYLEFT.search(text):
        return "copyleft"
    for name, rx in PERMISSIVE.items():
        if rx.search(text):
            return name
    return "unknown"


def check(base: pathlib.Path) -> list[str]:
    errs = []
    if not base.is_dir():
        return errs
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        names = {p.name for p in d.iterdir()}
        lic = [d / n for n in ("LICENSE", "COPYING", "LICENSE.txt") if n in names]
        if not lic:
            errs.append(f"{d.relative_to(base.parent if not base.is_relative_to(ROOT) else ROOT)}: 缺 LICENSE")
        else:
            kind = classify(lic[0].read_text(encoding="utf-8", errors="replace"))
            if kind == "copyleft":
                errs.append(f"{d.relative_to(base.parent if not base.is_relative_to(ROOT) else ROOT)}: LICENSE 是 GPL/LGPL/AGPL，规则只收宽松许可，删掉或换净室实现")
            elif kind == "unknown":
                errs.append(f"{d.relative_to(base.parent if not base.is_relative_to(ROOT) else ROOT)}: LICENSE 认不出是宽松许可（MIT/BSD/Apache-2.0/zlib/ISC），许可不明不得入库")
        sm = d / "SOURCE.md"
        if sm.is_file() and COPYLEFT.search(sm.read_text(encoding="utf-8")):
            errs.append(f"{sm.relative_to(base.parent if not base.is_relative_to(ROOT) else ROOT)}: 出处写着 GPL/LGPL/AGPL")
        if not sm.is_file() or not SRC.search(sm.read_text(encoding="utf-8")):
            errs.append(f"{d.relative_to(base.parent if not base.is_relative_to(ROOT) else ROOT)}: 缺 SOURCE.md 或其中没有 Source: repo@commit path")
        for f in d.rglob("*"):
            if f.suffix in CODE and "__pycache__" not in f.parts:
                text = f.read_text(encoding="utf-8", errors="replace")
                head = "\n".join(text.splitlines()[:15])
                if COPYLEFT.search("\n".join(text.splitlines()[:40])):
                    errs.append(f"{f.relative_to(base.parent if not base.is_relative_to(ROOT) else ROOT)}: 文件头带 GPL/LGPL/AGPL 声明")
                if not SRC.search(head):
                    errs.append(f"{f.relative_to(base.parent if not base.is_relative_to(ROOT) else ROOT)}: 前 15 行缺 Source: repo@commit path")
    ref = (ROOT / "docs/参考来源.md").read_text(encoding="utf-8")
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        if f"third_party/vendored/{d.name}" not in ref:
            errs.append(f"docs/参考来源.md 未登记 third_party/vendored/{d.name}")
    return errs


def check_sdk(base: pathlib.Path) -> list[str]:
    """third_party/ 下 make fetch 拉来的 SDK（vendored 以外）：每个目录顶层必须有许可文件，缺了算失败。"""
    errs = []
    if not base.is_dir():
        return errs
    for d in sorted(p for p in base.iterdir() if p.is_dir() and p.name != "vendored"):
        lic = re.compile(r"(^|/)(licen[cs]e|copying|eula)[^/]*$", re.I)
        archives = [f for f in d.iterdir() if f.suffix.lower() in (".pack", ".zip")]
        if archives and all(f.is_file() for f in d.iterdir()):        # 只放 CMSIS .pack 之类压缩包的目录：逐个查包里
            import zipfile
            for a in archives:
                try:
                    ok = any(lic.search(n) for n in zipfile.ZipFile(a).namelist())
                except zipfile.BadZipFile:
                    ok = False
                if not ok:
                    errs.append(f"third_party/{d.name}/{a.name}: 包里没有许可文件")
            continue
        if not any(lic.search(f.name) for f in d.iterdir()):
            errs.append(f"third_party/{d.name}: 顶层没有 LICENSE/COPYING/EULA，许可不明不得用")
    return errs


def main() -> int:
    errs = check(ROOT / "third_party" / "vendored") + check_sdk(ROOT / "third_party")
    for e in errs:
        print("✗", e)
    print("check_vendored:", "失败" if errs else "通过")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
