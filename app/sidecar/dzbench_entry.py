"""PyInstaller 入口（打包成 Tauri externalBin）。源码运行请用 python -m dzbench。"""
import os
import pathlib
import sys

# 便携包：exe 旁边的 repo/ 是随包带的工程仓库子集（仿真板、工具脚本、文档），没指定 DZBENCH_REPO 就用它
if getattr(sys, "frozen", False):
    os.environ.setdefault("PYTHONUTF8", "1")   # 子进程跑 tools/*.py 打中文；中文 Windows 控制台是 cp936，不设会 UnicodeEncodeError
    _repo = pathlib.Path(sys.executable).resolve().parent / "repo"
    if _repo.is_dir():
        os.environ.setdefault("DZBENCH_REPO", str(_repo))
    # 打包后 sys.executable 是 dzbench.exe 本身，跑 tools/*.py 要用随包的 python/（Windows 嵌入版）
    _py = pathlib.Path(sys.executable).resolve().parent / "python" / "python.exe"
    if _py.is_file():
        os.environ.setdefault("DZBENCH_PYTHON", str(_py))

from dzbench.__main__ import main  # noqa: E402

main()
