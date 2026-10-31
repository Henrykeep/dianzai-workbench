#!/usr/bin/env python3
"""打包产物路径 / 默认数据路径必须是 ASCII（统筹者决定：安装包、exe、zip、安装目录一律 XinTai；中文名 芯台 只做显示）。
查：tauri.conf.json（productName → 安装包名 / 安装目录 / 外壳 exe，mainBinaryName，externalBin，NSIS 钩子）、
tools/package_windows.sh 里落到 $STAGE / $WORK / $OUTDIR 的路径、CI 里 bundle.resources 的目标名、
侧车默认路径（$DZBENCH_HOME 未设时、projects / boards / flow / cubemx 默认目录）。
用法：python3 tools/check_ascii_paths.py [--selftest]"""
import json, os, pathlib, re, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
ok = lambda s: str(s).isascii()

def tauri_paths(conf: dict) -> list[tuple[str, str]]:
    pn, ver = conf["productName"], conf.get("version", "0")
    out = [("productName", pn), ("mainBinaryName", conf.get("mainBinaryName", pn)),
           ("NSIS 安装包", f"{pn}_{ver}_x64-setup.exe"), ("安装目录", f"%LOCALAPPDATA%\\{pn}")]
    b = conf.get("bundle", {})
    out += [("externalBin", x) for x in b.get("externalBin", [])]
    out += [("bundle.resources 目标", v) for v in (b.get("resources") or {}).values()] if isinstance(b.get("resources"), dict) else []
    h = b.get("windows", {}).get("nsis", {}).get("installerHooks")
    if h: out.append(("installerHooks", h))
    return out

def script_paths(text: str) -> list[tuple[str, str]]:
    # 写到产物里的路径：引号里以 $STAGE / $WORK / $OUTDIR 开头的，及 zip 打包的目录名
    out = [("package_windows.sh", m) for m in re.findall(r'"(\$(?:STAGE|WORK|OUTDIR)[^"]*)"', text)]
    out += [("package_windows.sh STAGE", m) for m in re.findall(r'STAGE="([^"]+)"', text)]
    out += [("package_windows.sh zip 目录", m) for m in re.findall(r'zip -\w+ "\$ZIP" "([^"]+)"', text)]
    return out

def workflow_paths(text: str) -> list[tuple[str, str]]:
    out = []
    for m in re.findall(r"echo '(\{.*?\})' > [\w.-]+\.json", text):
        out += [("CI bundle.resources 目标", v) for v in (json.loads(m).get("bundle", {}).get("resources") or {}).values()]
    return out

def default_paths() -> list[tuple[str, str]]:
    sys.path.insert(0, str(ROOT / "app/sidecar"))
    saved = {k: os.environ.pop(k, None) for k in ("DZBENCH_HOME", "DZ_BOARDS_DIR")}
    try:
        from dzbench import snapshots, paths
        out = [("$DZBENCH_HOME 默认", snapshots.base_dir()), ("projects_dir", paths.projects_dir()), ("boards_dir", paths.boards_dir())]
    finally:
        for k, v in saved.items():
            if v is not None: os.environ[k] = v
    # 源码里 Path.home() / "..." 拼出来的默认目录（flow、dz-cubemx、ti 等）
    for f in (ROOT / "app/sidecar/dzbench").rglob("*.py"):
        for m in re.findall(r'home\(\)\s*((?:/\s*"[^"]*"\s*)+)', f.read_text(encoding="utf-8")):
            out.append((f"{f.relative_to(ROOT)} home()", m))
    return out

def check(items) -> list[str]:
    return [f"✗ {k}: {v} 含非 ASCII" for k, v in items if not ok(v)]

def run() -> list[str]:
    items = tauri_paths(json.loads((ROOT / "app/src-tauri/tauri.conf.json").read_text(encoding="utf-8")))
    items += script_paths((ROOT / "tools/package_windows.sh").read_text(encoding="utf-8"))
    items += workflow_paths((ROOT / ".github/workflows/app-windows.yml").read_text(encoding="utf-8"))
    items += default_paths()
    return check(items)

def selftest():
    bad = {"productName": "芯台", "version": "1", "bundle": {"externalBin": ["binaries/dzbench"]}}
    assert len(check(tauri_paths(bad))) == 4, "productName 中文要牵连安装包名 / 目录"
    assert check(tauri_paths({"productName": "XinTai", "mainBinaryName": "x", "bundle": {}})) == []
    assert check(script_paths('ZIP="$OUTDIR/芯台-1.zip"\ncp a "$STAGE/使用说明.txt"')) and not check(script_paths('cp a "$STAGE/README.txt"'))
    assert check(workflow_paths("""echo '{"bundle":{"resources":{"a":"使用说明.txt"}}}' > r.json"""))
    print("check_ascii_paths selftest: ok")

if __name__ == "__main__":
    if "--selftest" in sys.argv: selftest(); sys.exit(0)
    errs = run()
    print("\n".join(errs) if errs else "✓ 打包产物与默认路径均为 ASCII（XinTai / .dzbench）")
    sys.exit(1 if errs else 0)
