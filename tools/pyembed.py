#!/usr/bin/env python3
"""Windows 安装包自带的嵌入版 CPython（#112 后续）。打包时由 tools/package_windows.sh 调用：

    python3 tools/pyembed.py pth <python312._pth>                     打开 site-packages（import site + Lib\\site-packages）
    python3 tools/pyembed.py manifest <wheelhouse目录> <3.12> <win_amd64> <requirements.txt>
                                                                       写 wheelhouse/manifest.json，doctor 用它核对解释器
安装目录布局：<安装目录>/python/python.exe（自带解释器）、<安装目录>/wheelhouse/、<安装目录>/repo/。
"""
from __future__ import annotations

import json
import pathlib
import sys

SITE_DIR = r"Lib\site-packages"


def enable_site(pth: pathlib.Path) -> None:
    """嵌入版 ._pth 默认不加载 site，pip 装进去的包导入不了；改成加载 site 并把 Lib\\site-packages 和仓库 tools 加进路径。幂等。"""
    lines = pth.read_text(encoding="utf-8").splitlines()
    out = []
    for ln in lines:
        if ln.strip() in ("#import site", "# import site"):
            ln = "import site"
        out.append(ln)
    if "import site" not in [x.strip() for x in out]:
        out.append("import site")
    if SITE_DIR not in [x.strip() for x in out]:
        out.insert(out.index("import site") if "import site" in out else len(out), SITE_DIR)
    pth.write_text("\r\n".join(out) + "\r\n", encoding="utf-8")


def write_manifest(wh: pathlib.Path, python_version: str, platform: str, req: pathlib.Path) -> dict:
    pk = {}
    for ln in req.read_text(encoding="utf-8").splitlines():
        ln = ln.split("#", 1)[0].strip()
        if ln:
            n, _, v = ln.partition("==")
            pk[n.strip()] = v.strip()
    m = {"python_version": python_version, "platform": platform, "implementation": "cp",
         "packages": pk, "bundled_python": "python/python.exe",
         "pip_wheel": next((f"_pip/{w.name}" for w in sorted((wh / "_pip").glob("pip-*.whl"))), None)}
    (wh / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return m


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["pth"] and len(a) == 2:
        enable_site(pathlib.Path(a[1]))
    elif a[:1] == ["manifest"] and len(a) == 5:
        write_manifest(pathlib.Path(a[1]), a[2], a[3], pathlib.Path(a[4]))
    else:
        sys.exit(__doc__)
