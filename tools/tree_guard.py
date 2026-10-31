#!/usr/bin/env python3
"""测试不许往仓库树里写东西：跑测试前后各拍一次仓库快照，多出来/变了的路径就失败。

  python3 tools/tree_guard.py snap  <快照文件>     # 测试前
  python3 tools/tree_guard.py check <快照文件>     # 测试后：有新文件/改动 → 退出码 1 并列出
  python3 tools/tree_guard.py --selftest

快照 = git status（含未跟踪文件，逐个文件）+ 被忽略但测试最容易漏删的地方（boards/ 下的、build/zz-test-*）。
build/ 其他产物、third_party/、缓存目录本来就是编译/拉取的输出，不算。
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
WATCH_IGNORED = ("boards/", "build/zz-test-", "examples/", "apps/", "tools/testdata/")


def snapshot(root: pathlib.Path = ROOT) -> list[str]:
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--ignored=matching", "-z"],
                         cwd=root, capture_output=True, check=True).stdout.decode("utf-8", "replace")
    keep = []
    for e in filter(None, out.split("\0")):
        st, path = e[:2], e[3:]
        if "__pycache__" in path or path.endswith(".pyc"):
            continue
        if st == "!!" and not path.startswith(WATCH_IGNORED):
            continue
        keep.append(e)
    # git 对被忽略的目录只报目录名（build/）：测试临时板的编译输出单独列
    keep += [f"!! {p.relative_to(root).as_posix()}/" for p in (root / "build").glob("zz-test-*")]
    return sorted(set(keep))


def diff(before: list[str], after: list[str]) -> list[str]:
    return sorted(set(after) - set(before))


def main(argv: list[str]) -> int:
    if argv[:1] == ["--selftest"]:
        with tempfile.TemporaryDirectory() as t:
            r = pathlib.Path(t)
            subprocess.run(["git", "init", "-q", str(r)], check=True)
            (r / ".gitignore").write_text("build/\n")
            (r / "boards").mkdir(); (r / "build").mkdir()
            b = snapshot(r)
            (r / "build" / "ok.o").write_text("x")                         # 普通编译产物：不算
            assert diff(b, snapshot(r)) == [], diff(b, snapshot(r))
            (r / "build" / "zz-test-1").mkdir(); (r / "build" / "zz-test-1" / "g").write_text("x")
            (r / "boards" / "zz-test-2").mkdir(); (r / "boards" / "zz-test-2" / "board.yaml").write_text("x")
            d = diff(b, snapshot(r))
            assert any("build/zz-test-1" in x for x in d) and any("boards/zz-test-2" in x for x in d), d
        print("tree_guard selftest: 通过")
        return 0
    if len(argv) != 2 or argv[0] not in ("snap", "check"):
        print(__doc__); return 2
    f = pathlib.Path(argv[1])
    if argv[0] == "snap":
        f.write_text("\n".join(snapshot()), encoding="utf-8")
        return 0
    d = diff(f.read_text(encoding="utf-8").splitlines(), snapshot())
    if d:
        print("✗ 测试往仓库树里写了东西（应写到临时目录 tmp_path / tempfile）：")
        for x in d:
            print("   ", x)
        return 1
    print("✓ tree_guard：测试没在仓库树里留下文件")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
