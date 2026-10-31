"""离线 Python 依赖自检（#112）。清单 = tools/wheelhouse.txt；安装只从本地 wheelhouse 装，不走网络。

    python3 tools/plantmodel.py doctor     → 打印 JSON {"ok": bool, "missing": [包名...], "install_cmd": "..."}，缺包时退出码 1
首次启动自检（侧车）调它即可；install_cmd 是离线命令，wheelhouse 路径：环境变量 DZ_WHEELHOUSE，否则 <仓库上一级>/wheelhouse
（Windows 安装包布局：<安装目录>/wheelhouse 与 <安装目录>/repo 并列），再否则仓库内 wheelhouse/。
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tools" / "wheelhouse.txt"
IMPORT_NAME = {"control": "control", "scipy": "scipy", "numpy": "numpy", "sysidentpy": "sysidentpy", "uncertainties": "uncertainties"}


def manifest() -> dict[str, str]:
    """{包名: 版本}，来自 tools/wheelhouse.txt。"""
    out = {}
    for ln in MANIFEST.read_text(encoding="utf-8").splitlines():
        ln = ln.split("#", 1)[0].strip()
        if ln:
            n, _, v = ln.partition("==")
            out[n.strip()] = v.strip()
    return out


def wheelhouse() -> pathlib.Path:
    if os.environ.get("DZ_WHEELHOUSE"):
        return pathlib.Path(os.environ["DZ_WHEELHOUSE"])
    for p in (ROOT.parent / "wheelhouse", ROOT / "wheelhouse"):
        if p.is_dir():
            return p
    return ROOT.parent / "wheelhouse"


def install_cmd() -> str:
    w = wheelhouse()
    return f'"{sys.executable}" -m pip install --no-index --find-links "{w}" -r "{w / "requirements.txt"}"'


def doctor() -> dict:
    missing = [n for n in manifest() if importlib.util.find_spec(IMPORT_NAME.get(n, n)) is None]
    return {"ok": not missing, "missing": missing, "install_cmd": install_cmd()}


def doctor_main() -> int:
    r = doctor()
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r["ok"] else 1


def require(*names: str) -> None:
    """缺包时给中文说明 + 离线安装命令后退出（退出码 1），不抛长串 Traceback。"""
    miss = [n for n in names if importlib.util.find_spec(IMPORT_NAME.get(n, n)) is None]
    if miss:
        sys.exit(f"缺少 Python 依赖：{'、'.join(miss)}（仿真对象建模需要）。\n"
                 f"请用安装包自带的离线依赖安装（不联网）：\n  {install_cmd()}\n"
                 f"也可运行 python3 tools/plantmodel.py doctor 查看缺哪些。")
