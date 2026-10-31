"""离线 Python 依赖自检（#112）。清单 = tools/wheelhouse.txt；安装只从本地 wheelhouse 装，不走网络。

    python3 tools/plantmodel.py doctor     → 打印 JSON {"ok", "missing", "install_cmd", "reason", "message_zh", "python"}，不 ok 时退出码 1
  reason: null | "missing" | "python_mismatch"（本解释器版本/平台与 wheelhouse/manifest.json 不符；此时不跑 pip，给中文说明）
  python: 推荐用的解释器（安装包自带 <安装目录>/python/python.exe 存在时优先它）
首次启动自检（侧车）调它即可；install_cmd 是离线命令，wheelhouse 路径：环境变量 DZ_WHEELHOUSE，否则 <仓库上一级>/wheelhouse
（Windows 安装包布局：<安装目录>/wheelhouse 与 <安装目录>/repo 并列），再否则仓库内 wheelhouse/。
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import sysconfig

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


def bundled_python() -> pathlib.Path:
    """安装包自带的嵌入版解释器：<安装目录>/python/python.exe（与 wheelhouse/ 并列）。"""
    return wheelhouse().parent / "python" / "python.exe"


def preferred_python() -> str:
    b = bundled_python()
    return str(b) if b.is_file() else sys.executable


def install_cmd(py: str | None = None) -> str:
    w = wheelhouse()
    py = py or preferred_python()
    if py == str(bundled_python()):
        # 嵌入版没有 pip：从 wheelhouse/_pip 里的 pip wheel 直接跑，装进 <安装目录>/python/Lib/site-packages
        whl = next(iter(sorted((w / "_pip").glob("pip-*.whl"))), w / "_pip" / "pip.whl")
        site = bundled_python().parent / "Lib" / "site-packages"
        return (f'"{py}" "{whl / "pip"}" install --no-index --find-links "{w}" --target "{site}" '
                f'-r "{w / "requirements.txt"}"')
    return f'"{py or preferred_python()}" -m pip install --no-index --find-links "{w}" -r "{w / "requirements.txt"}"'


def platform_tag() -> str:
    return sysconfig.get_platform().replace("-", "_").replace(".", "_")


def check_python(wh_manifest: dict) -> str | None:
    """与 wheelhouse/manifest.json 对照；不符时返回中文说明，相符返回 None。"""
    want_v, want_p = str(wh_manifest.get("python_version", "")), str(wh_manifest.get("platform", ""))
    have_v, have_p = f"{sys.version_info.major}.{sys.version_info.minor}", platform_tag()
    bp = bundled_python()
    if want_v and have_v != want_v:
        return f"本机 Python {have_v} 与离线包 {want_v} 不匹配，请使用安装目录自带的 {bp.parent.name}\\{bp.name}（{bp}）"
    if want_p and have_p != want_p:
        return f"本机 Python 平台 {have_p} 与离线包 {want_p} 不匹配，请使用安装目录自带的 {bp.parent.name}\\{bp.name}（{bp}）"
    return None


def import_smoke() -> dict[str, str]:
    """真的导入五个包（在子进程里，避免污染本进程）；返回 {包名: 错误摘要}。"""
    import subprocess
    code = ("import importlib,json,sys\nbad={}\nfor n,m in json.loads(sys.argv[1]).items():\n"
            "    try: importlib.import_module(m)\n    except Exception as e: bad[n]=type(e).__name__+': '+str(e)[:200]\n"
            "print(json.dumps(bad))")
    names = {n: IMPORT_NAME.get(n, n) for n in manifest()}
    try:
        r = subprocess.run([sys.executable, "-c", code, json.dumps(names)], capture_output=True, text=True, timeout=120)
        return json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {n: (r.stderr.strip()[-200:] or "导入子进程无输出") for n in names}
    except Exception as e:  # noqa: BLE001
        return {n: f"导入检查失败：{e}" for n in names}


def doctor() -> dict:
    mf = wheelhouse() / "manifest.json"
    if mf.is_file():
        msg = check_python(json.loads(mf.read_text(encoding="utf-8")))
        if msg:
            return {"ok": False, "reason": "python_mismatch", "message_zh": msg, "missing": [],
                    "python": str(bundled_python()), "install_cmd": install_cmd(str(bundled_python()))}
    missing = [n for n in manifest() if importlib.util.find_spec(IMPORT_NAME.get(n, n)) is None]
    if not missing:
        bad = import_smoke()
        if bad:
            return {"ok": False, "reason": "import_failed", "missing": [], "import_errors": bad,
                    "message_zh": "以下依赖装了但导入失败：" + "；".join(f"{k}（{v}）" for k, v in bad.items())
                                  + "。请运行 install_cmd 离线重装",
                    "python": preferred_python(), "install_cmd": install_cmd()}
    return {"ok": not missing, "reason": "missing" if missing else None,
            "message_zh": f"缺少 Python 依赖：{'、'.join(missing)}，请运行 install_cmd 离线安装" if missing else "",
            "missing": missing, "python": preferred_python(), "install_cmd": install_cmd()}


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
