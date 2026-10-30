"""PyInstaller 入口（打包成 Tauri externalBin）。源码运行请用 python -m dzbench。"""
import os
import pathlib
import sys

# 安装包 / 便携包：exe 旁边的 repo/ 是随包带的工程仓库子集（仿真板、工具脚本、文档），没指定 DZBENCH_REPO 就用它
if getattr(sys, "frozen", False):
    os.environ.setdefault("PYTHONUTF8", "1")   # 子进程跑 tools/*.py 打中文；中文 Windows 控制台是 cp936，不设会 UnicodeEncodeError
    _repo = pathlib.Path(sys.executable).resolve().parent / "repo"
    if _repo.is_dir():
        os.environ.setdefault("DZBENCH_REPO", str(_repo))
    # 打包后 sys.executable 就是 dzbench.exe：侧车用 [sys.executable, "tools/x.py", ...] 跑工具脚本时，在本进程里执行它
    if len(sys.argv) > 1 and sys.argv[1].endswith(".py"):
        import runpy
        for _s in (sys.stdout, sys.stderr):   # 本进程里 PYTHONUTF8 已来不及生效：和源码运行（子进程 PYTHONUTF8=1）一样输出 UTF-8
            if _s is not None and hasattr(_s, "reconfigure"):
                _s.reconfigure(encoding="utf-8", errors="replace")
        import csv, difflib, filecmp, html, ast, dataclasses, hashlib, random, xml.etree.ElementTree, itertools, tempfile, copy  # noqa: F401,E401  让 PyInstaller 收进 tools/*.py 用到的标准库
        import yaml, jsonschema  # noqa: F401,E401
        _tool = pathlib.Path(sys.argv[1]).resolve()
        sys.argv = [str(_tool), *sys.argv[2:]]
        sys.path.insert(0, str(_tool.parent))
        runpy.run_path(str(_tool), run_name="__main__")
        sys.exit(0)

from dzbench.__main__ import main  # noqa: E402

main()
