#!/usr/bin/env python3
"""check_vendored 许可扫描自测：GPL/AGPL/LGPL、无许可、认不出的许可都必须失败；MIT/BSD/Apache 通过。"""
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_vendored as C  # noqa: E402

MIT = "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy\n"
GPL3 = "                    GNU GENERAL PUBLIC LICENSE\n                       Version 3, 29 June 2007\n"
AGPL = "                    GNU AFFERO GENERAL PUBLIC LICENSE\n"
LGPL = "                   GNU LESSER GENERAL PUBLIC LICENSE\n"
SRC = "Source: github.com/x/y@abcdef1 a.py\n"


def run(lic, code="# Source: github.com/x/y@abcdef1 a.py\n", source=SRC):
    with tempfile.TemporaryDirectory() as t:
        d = pathlib.Path(t) / "lib"
        d.mkdir()
        if lic is not None:
            (d / "LICENSE").write_text(lic)
        (d / "SOURCE.md").write_text(source)
        (d / "a.py").write_text(code)
        return [e for e in C.check(pathlib.Path(t)) if "参考来源" not in e]


def main():
    fails = []
    cases = [
        ("MIT 通过", run(MIT), False),
        ("BSD 通过", run("Redistribution and use in source and binary forms, with or without\n"), False),
        ("Apache 通过", run("Apache License\nVersion 2.0, January 2004\n".replace("\n", " ", 1)), False),
        ("GPL-3.0 失败（pid_helper 同款）", run(GPL3), True),
        ("AGPL 失败", run(AGPL), True),
        ("LGPL 失败", run(LGPL), True),
        ("缺 LICENSE 失败", run(None), True),
        ("认不出的许可失败", run("All rights reserved.\n"), True),
        ("MIT 目录里夹 GPL 文件头失败", run(MIT, code="# Source: github.com/x/y@abcdef1 a.py\n# SPDX-License-Identifier: GPL-3.0-or-later\n"), True),
        ("SOURCE.md 写 GPL 失败", run(MIT, source=SRC + "许可：GPL-3.0\n"), True),
    ]
    for name, errs, want in cases:
        ok = bool(errs) == want
        print("✓" if ok else "✗", name, errs if not ok else "")
        if not ok:
            fails.append(name)
    with tempfile.TemporaryDirectory() as tp:
        tp = pathlib.Path(tp)
        (tp / "sdk_ok").mkdir(); (tp / "sdk_ok" / "license_x.txt").write_text("x")
        (tp / "sdk_bad").mkdir(); (tp / "sdk_bad" / "readme.md").write_text("x")
        (tp / "tool_ok" / "dist").mkdir(parents=True); (tp / "tool_ok" / "dist" / "license.txt").write_text("x")   # 安装器装的工具：许可在 dist/
        e = C.check_sdk(tp)
        ok = len(e) == 1 and "sdk_bad" in e[0]
        print("✓" if ok else "✗", "SDK 目录缺许可文件失败、有则通过", "" if ok else e)
        if not ok:
            fails.append("sdk")
    with tempfile.TemporaryDirectory() as tp:
        tp = pathlib.Path(tp)
        (tp / ".github" / "workflows").mkdir(parents=True)
        (tp / ".github" / "workflows" / "w.yml").write_text("run: pyinstaller --paths third_party/vendored/pid_helper x\n")
        (tp / "tools").mkdir(); (tp / "tools" / "a.py").write_text("from k230_edc_skill import x\n")
        (tp / "tools" / "ok.sh").write_text("# 致谢 PID_Helper 思路\n")
        e = C.check_removed_refs(tp)
        ok = len(e) == 2 and any("w.yml" in x for x in e) and any("a.py" in x for x in e)
        print("✓" if ok else "✗", "workflow/构建文件引用已删 GPL 目录失败（致谢文字不算）", "" if ok else e)
        if not ok:
            fails.append("removed_refs")
    def git_repo(t):
        r = pathlib.Path(t)
        subprocess.run(["git", "init", "-q", str(r)], check=True)
        return r

    def git_add(r, *paths):
        subprocess.run(["git", "-C", str(r), "add", "-f", *paths], check=True)

    with tempfile.TemporaryDirectory() as t:       # 已删目录下只有未跟踪的 __pycache__：通过 + 残留目录警告
        r = git_repo(t)
        v = r / "third_party" / "vendored"
        pc = v / "pid_helper" / "__pycache__"
        pc.mkdir(parents=True); (pc / "pid.cpython-312.pyc").write_bytes(b"GPL\0")
        (v / "pid_helper" / "LICENSE").write_text(GPL3)       # 未跟踪的 GPL 残留也不算失败
        w = []
        e = C.check(v, r, w)
        ok = not e and w == ["残留目录 third_party/vendored/pid_helper：该目录已从仓库移除，请删除"]
        print("✓" if ok else "✗", "未跟踪的 pid_helper/__pycache__ 不失败，报残留目录警告", "" if ok else (e, w))
        if not ok:
            fails.append("leftover")
    with tempfile.TemporaryDirectory() as t:       # 跟踪的 GPL 文件仍失败；未跟踪的杂物目录被忽略
        r = git_repo(t)
        v = r / "third_party" / "vendored"
        (v / "lib").mkdir(parents=True)
        (v / "lib" / "LICENSE").write_text(GPL3); (v / "lib" / "SOURCE.md").write_text(SRC)
        (v / "lib" / "a.py").write_text("# Source: github.com/x/y@abcdef1 a.py\n")
        (v / "junk" / "__pycache__").mkdir(parents=True); (v / "junk" / "__pycache__" / "x.pyc").write_bytes(b"x")
        git_add(r, "third_party/vendored/lib")
        w = []
        e = [x for x in C.check(v, r, w) if "参考来源" not in x]
        ok = any("GPL" in x and "lib" in x for x in e) and not any("junk" in x for x in e) and not w
        print("✓" if ok else "✗", "跟踪的 GPL 许可仍失败，未跟踪杂物目录忽略", "" if ok else (e, w))
        if not ok:
            fails.append("tracked_gpl")
    with tempfile.TemporaryDirectory() as t:       # 已删目录里有跟踪文件：失败，不是警告
        r = git_repo(t)
        v = r / "third_party" / "vendored" / "pid_helper"
        v.mkdir(parents=True); (v / "pid.py").write_text("# GPL-3.0\n")
        git_add(r, "third_party/vendored/pid_helper/pid.py")
        w = []
        e = C.check(v.parent, r, w)
        ok = any("已因许可删除" in x for x in e) and not w
        print("✓" if ok else "✗", "已删目录有跟踪文件则失败", "" if ok else (e, w))
        if not ok:
            fails.append("tracked_removed")
    real = C.check_removed_refs(C.ROOT) + C.check(C.ROOT / "third_party" / "vendored", C.ROOT) + C.check_sdk(C.ROOT / "third_party")
    print("✓ 仓库现有 vendored 全部通过" if not real else f"✗ 仓库 vendored: {real}")
    print("test_check_vendored:", "失败" if fails or real else "通过")
    return 1 if fails or real else 0


if __name__ == "__main__":
    sys.exit(main())
