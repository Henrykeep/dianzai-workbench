"""离线 Python 依赖自检（#112 / #137）。清单 = tools/wheelhouse.txt；安装只从本地 wheelhouse 装，不走网络。

    python3 tools/plantmodel.py doctor     → JSON {ok, reason, message_zh, missing, python, install_cmd}，不 ok 时退出码 1
    python  tools/pydeps.py doctor         同上
    python  tools/pydeps.py repair         按 install_cmd 离线重装；pip 的英文报错一律翻成中文说明（JSON {ok, reason, message_zh}）
    python  tools/pydeps.py wheelhouse --platform <tag> [--python-version 3.12] [-o 目录]
                                           在联网的机器上为目标平台（如 manylinux2014_x86_64 / macosx_11_0_arm64 / win_amd64）
                                           备一份离线 wheelhouse（含 manifest.json），拷到断网机器上 --no-index 安装
reason: null | "missing" | "import_failed" | "python_mismatch" | "wheelhouse_missing"
  python_mismatch：本解释器 主.次 版本/平台与 wheelhouse/manifest.json 不符（不跑 pip，按操作系统给中文办法）
  wheelhouse_missing：缺包且找不到 wheelhouse 目录；install_cmd 为 null —— 绝不给指向不存在路径的命令
wheelhouse 位置：环境变量 DZ_WHEELHOUSE；否则自带解释器旁边（<安装目录>/python/python.exe → <安装目录>/wheelhouse）；
否则 <仓库上一级>/wheelhouse（安装包布局 <安装目录>/repo）；否则仓库内 wheelhouse/。都不存在 → 视为没有。
python：推荐解释器。Windows 安装包里是 <安装目录>/python/python.exe（存在时优先）。
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import sysconfig

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tools" / "wheelhouse.txt"
IMPORT_NAME = {"control": "control", "scipy": "scipy", "numpy": "numpy", "sysidentpy": "sysidentpy", "uncertainties": "uncertainties"}
PY_WANT = "3.12"   # Windows 安装包自带的版本；源码运行时 manifest.json 里的 python_version 优先


def manifest() -> dict[str, str]:
    """{包名: 版本}，来自 tools/wheelhouse.txt。"""
    out = {}
    for ln in MANIFEST.read_text(encoding="utf-8").splitlines():
        ln = ln.split("#", 1)[0].strip()
        if ln:
            n, _, v = ln.partition("==")
            out[n.strip()] = v.strip()
    return out


def os_kind() -> str:
    """windows / linux / darwin；DZ_DOCTOR_OS 只给测试覆盖用。"""
    k = os.environ.get("DZ_DOCTOR_OS") or sys.platform
    return "windows" if k.startswith("win") else "darwin" if k.startswith("darwin") else "linux"


def wheelhouse() -> pathlib.Path | None:
    if os.environ.get("DZ_WHEELHOUSE"):
        p = pathlib.Path(os.environ["DZ_WHEELHOUSE"])
        return p if p.is_dir() else None
    exe = pathlib.Path(sys.executable).resolve()
    for p in (exe.parent.parent / "wheelhouse" if exe.parent.name == "python" else None,
              ROOT.parent / "wheelhouse", ROOT / "wheelhouse"):
        if p is not None and p.is_dir():
            return p
    return None


def install_dir() -> pathlib.Path:
    w = wheelhouse()
    if w is not None:
        return w.parent
    if os.environ.get("DZ_WHEELHOUSE"):
        return pathlib.Path(os.environ["DZ_WHEELHOUSE"]).parent
    return ROOT.parent


def bundled_python() -> pathlib.Path:
    """安装包自带的嵌入版解释器：<安装目录>/python/python.exe（与 wheelhouse/ 并列）。"""
    return install_dir() / "python" / "python.exe"


def preferred_python() -> str:
    b = bundled_python()
    return str(b) if b.is_file() else sys.executable


def install_argv(py: str | None = None) -> list[str] | None:
    """离线安装命令（参数列表）；wheelhouse 不存在 → None。"""
    w = wheelhouse()
    if w is None:
        return None
    py = py or preferred_python()
    if py == str(bundled_python()):
        # 嵌入版没有 pip：从 wheelhouse/_pip 里的 pip wheel 直接跑，装进 <安装目录>/python/Lib/site-packages
        whl = next(iter(sorted((w / "_pip").glob("pip-*.whl"))), None)
        if whl is None:
            return None
        site = bundled_python().parent / "Lib" / "site-packages"
        return [py, str(whl / "pip"), "install", "--no-index", "--find-links", str(w), "--target", str(site),
                "-r", str(w / "requirements.txt")]
    req = w / "requirements.txt"
    return [py, "-m", "pip", "install", "--no-index", "--find-links", str(w), "-r", str(req if req.is_file() else MANIFEST)]


def install_cmd(py: str | None = None) -> str | None:
    a = install_argv(py)
    return None if a is None else " ".join(f'"{x}"' if i == 0 or " " in x or "/" in x or "\\" in x else x for i, x in enumerate(a))


def platform_tag() -> str:
    return sysconfig.get_platform().replace("-", "_").replace(".", "_")


def have_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def source_guide(want_v: str) -> str:
    """Linux / macOS 源码运行（没有自带解释器）时的中文办法。"""
    plat = "macos" if os_kind() == "darwin" else "linux"
    get_py = ("可用 brew install python@" + want_v) if os_kind() == "darwin" else ("可用系统包管理器装 python" + want_v + "（如 apt install python" + want_v + " python" + want_v + "-venv）")
    return (f"办法一（能联网）：装 Python {want_v}（{get_py}），在仓库根目录执行 "
            f"python{want_v} -m venv .venv && .venv/bin/pip install -r tools/wheelhouse.txt，之后用 .venv/bin/python 运行。"
            f"办法二（断网）：在一台联网的机器上执行 python3 tools/pydeps.py wheelhouse --platform {plat} --python-version {want_v} -o wheelhouse，"
            f"把 wheelhouse 目录拷过来，再执行 .venv/bin/pip install --no-index --find-links wheelhouse -r tools/wheelhouse.txt。")


def plat_ok(have: str, want: str) -> bool:
    """manylinux*_x86_64 对 linux_x86_64、macosx_*_arm64 对 macosx_*_arm64 视为同一平台。"""
    if have == want:
        return True
    arch = lambda t: t.split("_", 2)[-1] if t.startswith("macosx") else t.split("_", 1)[-1]  # noqa: E731
    if want.startswith("manylinux") and have.startswith("linux"):
        return want.endswith(have.split("_", 1)[1])
    if want.startswith("macosx") and have.startswith("macosx"):
        return arch(want) == arch(have) or have.endswith("universal2")
    return False


def check_python(wh_manifest: dict) -> str | None:
    """与 wheelhouse/manifest.json 对照；不符时返回中文说明，相符返回 None。"""
    want_v, want_p = str(wh_manifest.get("python_version", "")), str(wh_manifest.get("platform", ""))
    have_v, have_p = have_version(), platform_tag()
    if want_v and have_v != want_v:
        head = f"本机 Python {have_v} 与离线包 {want_v} 不匹配"
    elif want_p and not any(plat_ok(have_p, x) for x in want_p.split(",")):
        head = f"本机 Python 平台 {have_p} 与离线包 {want_p} 不匹配"
    else:
        return None
    if os_kind() == "windows":
        bp = bundled_python()
        if bp.is_file() or want_p.startswith("win"):
            return f"{head}，请使用安装目录自带的 python\\python.exe（{bp}）"
    return f"{head}（这份离线包是给 {want_p or '其他平台'} 的，本机用不了）。" + source_guide(want_v or PY_WANT)


def import_smoke() -> dict[str, str]:
    """真的导入五个包（在子进程里，避免污染本进程）；返回 {包名: 错误摘要}。"""
    code = ("import importlib,json,sys\nbad={}\nfor n,m in json.loads(sys.argv[1]).items():\n"
            "    try: importlib.import_module(m)\n    except Exception as e: bad[n]=type(e).__name__+': '+str(e)[:200]\n"
            "print(json.dumps(bad))")
    names = {n: IMPORT_NAME.get(n, n) for n in manifest()}
    try:
        r = subprocess.run([sys.executable, "-c", code, json.dumps(names)], capture_output=True, text=True, timeout=120)
        return json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {n: (r.stderr.strip()[-200:] or "导入子进程无输出") for n in names}
    except Exception as e:  # noqa: BLE001
        return {n: f"导入检查失败：{e}" for n in names}


def no_wheelhouse_msg() -> str:
    if os_kind() == "windows":
        return f"找不到离线依赖目录 wheelhouse（应在 {install_dir() / 'wheelhouse'}），安装包可能不完整，请重新运行安装程序。"
    return "找不到离线依赖目录 wheelhouse（源码运行不带它）。" + source_guide(PY_WANT)


def _res(ok, reason, msg, missing=(), **kw) -> dict:
    return {"ok": ok, "reason": reason, "message_zh": msg, "missing": list(missing),
            "python": preferred_python(), "install_cmd": install_cmd(), **kw}


def doctor() -> dict:
    w = wheelhouse()
    if w is not None and (w / "manifest.json").is_file():
        msg = check_python(json.loads((w / "manifest.json").read_text(encoding="utf-8")))
        if msg:
            win = os_kind() == "windows"
            return {"ok": False, "reason": "python_mismatch", "message_zh": msg, "missing": [],
                    "python": str(bundled_python()) if win else None,
                    "install_cmd": install_cmd(str(bundled_python())) if win and bundled_python().is_file() else None}
    missing = [n for n in manifest() if importlib.util.find_spec(IMPORT_NAME.get(n, n)) is None]
    if missing and w is None:
        return {**_res(False, "wheelhouse_missing", f"缺少 Python 依赖：{'、'.join(missing)}。" + no_wheelhouse_msg(), missing),
                "install_cmd": None}
    if missing:
        return _res(False, "missing", f"缺少 Python 依赖：{'、'.join(missing)}，请运行 install_cmd 离线安装", missing)
    bad = import_smoke()
    if bad:
        hint = "请运行 install_cmd 离线重装" if w is not None else no_wheelhouse_msg()
        return _res(False, "import_failed", "以下依赖装了但导入失败：" + "；".join(f"{k}（{v}）" for k, v in bad.items()) + "。" + hint,
                    import_errors=bad)
    return _res(True, None, "")


def explain_pip(out: str, rc: int) -> dict:
    """pip 输出 → 中文结论（不把英文报错原样甩给用户）。"""
    if rc == 0:
        return {"ok": True, "reason": None, "message_zh": "离线依赖已装好"}
    low = out.lower()
    if "no matching distribution" in low or "could not find a version" in low or "is not a supported wheel" in low:
        return {"ok": False, "reason": "python_mismatch",
                "message_zh": f"离线包里没有适合本机 Python {have_version()}（{platform_tag()}）的版本：离线包是给别的 Python 版本或平台打的。"
                              + ("请使用安装目录自带的 python\\python.exe。" if os_kind() == "windows" else source_guide(PY_WANT))}
    if "errno 2" in low or "no such file" in low or "does not exist" in low:
        return {"ok": False, "reason": "wheelhouse_missing", "message_zh": "离线依赖文件不全：" + no_wheelhouse_msg()}
    tail = [ln for ln in out.strip().splitlines() if ln.strip()][-1:] or [""]
    return {"ok": False, "reason": "pip_failed", "message_zh": f"离线安装失败（退出码 {rc}），pip 最后一行：{tail[0][:200]}"}


def repair() -> dict:
    d = doctor()
    if d["reason"] in ("python_mismatch", "wheelhouse_missing"):
        return {"ok": False, "reason": d["reason"], "message_zh": d["message_zh"]}
    a = install_argv()
    if a is None:
        return {"ok": False, "reason": "wheelhouse_missing", "message_zh": no_wheelhouse_msg()}
    try:
        r = subprocess.run(a, capture_output=True, text=True, env={**os.environ, "PIP_NO_INDEX": "1"}, timeout=1800)
        return explain_pip(r.stdout + r.stderr, r.returncode)
    except OSError as e:
        return explain_pip(f"[Errno 2] {e}", 1)


PLATFORM_PRESETS = {"linux": ["manylinux2014_x86_64"], "macos": ["macosx_11_0_arm64", "macosx_10_9_x86_64"],
                    "windows": ["win_amd64"]}


def expand_platforms(tags: list[str]) -> list[str]:
    out = []
    for t in tags:
        for x in PLATFORM_PRESETS.get(t, [t]):
            if x not in out:
                out.append(x)
    return out


def wheelhouse_argv(platforms: list[str], python_version: str, out: pathlib.Path, req: pathlib.Path) -> list[str]:
    a = [sys.executable, "-m", "pip", "download", "--only-binary=:all:"]
    for t in expand_platforms(platforms):
        a += ["--platform", t]
    return a + ["--python-version", python_version, "--implementation", "cp", "-d", str(out), "-r", str(req)]


def build_wheelhouse(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="pydeps.py wheelhouse", description="在联网机器上为目标平台备离线 wheelhouse")
    ap.add_argument("--platform", action="append", required=True,
                    help="可重复；预设 linux=manylinux2014_x86_64，macos=macosx_11_0_arm64+macosx_10_9_x86_64，windows=win_amd64")
    ap.add_argument("--python-version", default=PY_WANT)
    ap.add_argument("-o", "--out", default="wheelhouse")
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    req = out / "requirements.txt"
    req.write_text("".join(f"{n}=={v}\n" for n, v in manifest().items()), encoding="utf-8")
    r = subprocess.run(wheelhouse_argv(a.platform, a.python_version, out, req), capture_output=True, text=True)
    if r.returncode:
        print(json.dumps(explain_pip(r.stdout + r.stderr, r.returncode), ensure_ascii=False)); return 1
    sys.path.insert(0, str(ROOT / "tools"))
    import pyembed
    plats = expand_platforms(a.platform)
    pyembed.write_manifest(out, a.python_version, ",".join(plats), req)
    print(f"✓ 离线 wheelhouse → {out}（{', '.join(plats)}, Python {a.python_version}）；断网机器上：pip install --no-index --find-links {out} -r {req}")
    return 0


def doctor_main() -> int:
    r = doctor()
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r["ok"] else 1


def require(*names: str) -> None:
    """缺包时给中文说明 + 离线安装办法后退出（退出码 1），不抛长串 Traceback。"""
    miss = [n for n in names if importlib.util.find_spec(IMPORT_NAME.get(n, n)) is None]
    if miss:
        c = install_cmd()
        how = f"请用安装包自带的离线依赖安装（不联网）：\n  {c}\n" if c else no_wheelhouse_msg() + "\n"
        sys.exit(f"缺少 Python 依赖：{'、'.join(miss)}（仿真对象建模需要）。\n{how}"
                 f"也可运行 python3 tools/plantmodel.py doctor 查看缺哪些。")


if __name__ == "__main__":
    cmd = sys.argv[1:2]
    if cmd == ["doctor"]:
        sys.exit(doctor_main())
    if cmd == ["repair"]:
        res = repair(); print(json.dumps(res, ensure_ascii=False)); print(res["message_zh"], file=sys.stderr)
        sys.exit(0 if res["ok"] else 1)
    if cmd == ["wheelhouse"]:
        sys.exit(build_wheelhouse(sys.argv[2:]))
    sys.exit(__doc__)
