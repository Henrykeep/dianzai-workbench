#!/usr/bin/env python3
"""check_vendored 许可扫描自测：GPL/AGPL/LGPL、无许可、认不出的许可都必须失败；MIT/BSD/Apache 通过。"""
import pathlib
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
    real = C.check(C.ROOT / "third_party" / "vendored") + C.check_sdk(C.ROOT / "third_party")
    print("✓ 仓库现有 vendored 全部通过" if not real else f"✗ 仓库 vendored: {real}")
    print("test_check_vendored:", "失败" if fails or real else "通过")
    return 1 if fails or real else 0


if __name__ == "__main__":
    sys.exit(main())
