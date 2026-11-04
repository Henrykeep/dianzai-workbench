#!/usr/bin/env python3
"""检查 third_party/vendored/ 每个来源都有 LICENSE、SOURCE.md，代码文件都有 Source: 头；
许可扫描：LICENSE 必须是可识别的宽松许可（MIT/BSD/Apache-2.0/zlib/ISC）或第 3 版 GPL/LGPL/AGPL
（芯台整体按 AGPL-3.0-or-later 发布，兼容；统筹者 2026-11-04 决定）。GPL 第 2 版（无 or-later）或认不出许可即失败。自测：tools/test_check_vendored.py。"""
import pathlib
import re
import subprocess
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


V3_HDR = re.compile(r"\b(A|L)?GPL-?v?3(\.0)?(-or-later|\+|-only)?\b|version\s+3\b", re.I)
V2_ONLY = re.compile(r"GPL-?v?2(\.\d)?(-only)?\b(?!\+|-or-later)|version\s+2(\.\d)?\s+only|GPL-2\.0(?!-or-later|\+)", re.I)


def header_copyleft_bad(head: str) -> bool:
    """文件头有 copyleft 声明，但不是 v3 系列（或明确写了 v2-only）即为不合格。"""
    if not COPYLEFT.search(head):
        return False
    return bool(V2_ONLY.search(head)) or not V3_HDR.search(head)


COPYLEFT3 = re.compile(r"GNU\s+(AFFERO\s+|LESSER\s+)?GENERAL\s+PUBLIC\s+LICENSE\s+Version\s+3\b", re.I)


def classify(text: str) -> str:
    """'GPL-3-family'（与本仓库 AGPL-3.0-or-later 兼容）/ 'copyleft'（其它 GPL 版本，不兼容）/ 许可名 / 'unknown'。"""
    if COPYLEFT3.search(text):
        return "GPL-3-family"
    if COPYLEFT.search(text):
        return "copyleft"
    for name, rx in PERMISSIVE.items():
        if rx.search(text):
            return name
    return "unknown"


def tracked(root: pathlib.Path) -> set[str] | None:
    """root 下 git 跟踪的文件（相对 root 的 posix 路径）；不是 git 仓库时返回 None（退回按磁盘扫描）。"""
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--full-name", "."], capture_output=True, check=True).stdout
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, check=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    pre = pathlib.Path(root).resolve().relative_to(pathlib.Path(top).resolve()).as_posix()
    pre = "" if pre == "." else pre + "/"
    return {n[len(pre):] for n in out.decode("utf-8", "replace").split("\0") if n and n.startswith(pre)}


def _files(d: pathlib.Path, root: pathlib.Path, tr: set[str] | None) -> list[pathlib.Path]:
    if tr is None:
        return [f for f in d.rglob("*") if f.is_file() and "__pycache__" not in f.parts]
    pre = d.relative_to(root).as_posix() + "/"
    return [root / n for n in sorted(tr) if n.startswith(pre)]


def check(base: pathlib.Path, root: pathlib.Path | None = None, warns: list[str] | None = None) -> list[str]:
    """只扫 git 跟踪的文件（root 是 git 仓库时）；未跟踪的 __pycache__ 等杂物不参与判定。
    已删除的许可违规目录（REMOVED）若仍在磁盘上但没有跟踪文件：记为残留目录警告（写入 warns），不算失败。"""
    errs = []
    if not base.is_dir():
        return errs
    root = root or (ROOT if base.resolve().is_relative_to(ROOT) else base.parent)
    tr = tracked(root)
    rel = lambda p: p.relative_to(root).as_posix()  # noqa: E731
    dirs = []
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        files = _files(d, root, tr)
        if d.name in REMOVED and tr is not None and not files:
            if warns is not None:
                warns.append(f"残留目录 {rel(d)}：该目录已从仓库移除，请删除")
            continue
        if not files:          # 未跟踪的杂物目录：不属于仓库，不检查
            continue
        dirs.append(d)
        names = {f.relative_to(d).as_posix() for f in files}
        lic = [d / n for n in ("LICENSE", "COPYING", "LICENSE.txt") if n in names]
        if d.name in REMOVED:
            errs.append(f"{rel(d)}: 已因许可删除的目录又有文件被 git 跟踪，删掉（git rm -r）")
        if not lic:
            errs.append(f"{rel(d)}: 缺 LICENSE")
        else:
            kind = classify(lic[0].read_text(encoding="utf-8", errors="replace"))
            if kind == "copyleft":
                errs.append(f"{rel(d)}: LICENSE 是 GPL 第 3 版以外的 copyleft 许可，与本仓库 AGPL-3.0-or-later 不兼容，删掉或换净室实现")
            elif kind == "unknown":
                errs.append(f"{rel(d)}: LICENSE 认不出是宽松许可（MIT/BSD/Apache-2.0/zlib/ISC），许可不明不得入库")
        sm = d / "SOURCE.md"
        has_sm = "SOURCE.md" in names and sm.is_file()
        if has_sm and header_copyleft_bad(sm.read_text(encoding="utf-8")):
            errs.append(f"{rel(sm)}: 出处写的 copyleft 许可不是第 3 版系列")
        if not has_sm or not SRC.search(sm.read_text(encoding="utf-8")):
            errs.append(f"{rel(d)}: 缺 SOURCE.md 或其中没有 Source: repo@commit path")
        for f in files:
            if f.suffix in CODE and "__pycache__" not in f.parts and f.is_file():
                text = f.read_text(encoding="utf-8", errors="replace")
                head = "\n".join(text.splitlines()[:15])
                if header_copyleft_bad("\n".join(text.splitlines()[:40])):
                    errs.append(f"{rel(f)}: 文件头的 copyleft 声明不是 GPL/LGPL/AGPL 第 3 版系列（如 GPL-2-only），不得入库")
                if not SRC.search(head):
                    errs.append(f"{rel(f)}: 前 15 行缺 Source: repo@commit path")
    refp = ROOT / "docs/参考来源.md"
    ref = refp.read_text(encoding="utf-8") if refp.is_file() else ""
    for d in dirs:
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
        # 安装器装的工具（如 make fetch 装的 TI SysConfig）许可在 dist/license.txt：顶层或 dist/ 下有即可
        tops = list(d.iterdir()) + (list((d / "dist").iterdir()) if (d / "dist").is_dir() else [])
        if not any(lic.search(f.name) for f in tops):
            errs.append(f"third_party/{d.name}: 顶层没有 LICENSE/COPYING/EULA，许可不明不得用")
    return errs


# 因许可删掉的目录：构建 / 打包 / 运行路径里再出现就失败（文档里的致谢不算，见 docs/参考来源.md）
REMOVED = ("pid_helper", "k230_edc_skill")
REMOVED_RE = re.compile(r"third_party/vendored/(" + "|".join(REMOVED) + r")\b|^\s*(from|import)\s+(" + "|".join(REMOVED) + r")\b", re.M)
BUILD_GLOBS = (".github/workflows/*.yml", ".github/workflows/*.yaml", "Makefile", "mk/*.mk", "tools/*.sh", "tools/*.py",
               "**/*.spec", "**/*.projectspec", "app/src-tauri/*.json", "app/src-tauri/*.toml", "app/sidecar/**/*.py",
               "app/sidecar/requirements*.txt", "app/ui/package.json", "packaging/**/*")
SELF = {"tools/check_vendored.py", "tools/test_check_vendored.py"}


def check_removed_refs(base: pathlib.Path) -> list[str]:
    errs, seen = [], set()
    tr = tracked(base)
    for g in BUILD_GLOBS:
        for f in base.glob(g):
            rel = f.relative_to(base).as_posix()
            if rel in seen or rel in SELF or (tr is not None and rel not in tr) or not f.is_file() or "node_modules" in rel or "/tests/" in rel:
                continue
            seen.add(rel)
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            for m in REMOVED_RE.finditer(text):
                ln = text.count("\n", 0, m.start()) + 1
                errs.append(f"{rel}:{ln} 引用已删除的许可违规目录 {m.group(0).strip()} · 原因：构建/打包/运行路径不得再指向它")
    return errs


def main() -> int:
    warns: list[str] = []
    errs = check(ROOT / "third_party" / "vendored", ROOT, warns) + check_sdk(ROOT / "third_party") + check_removed_refs(ROOT)
    for w in warns:
        print(f"⚠ [licenses/leftover] {w}（未被 git 跟踪，不影响门禁；可执行 rm -rf 该目录）")
    for e in errs:
        print(f"✗ [licenses/vendored] {e} · 处理：删掉该目录或换宽松许可/净室实现（规则见 third_party/vendored/README.md）")
    print("check_vendored:", "失败" if errs else "通过")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
