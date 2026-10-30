#!/usr/bin/env python3
"""Python 依赖许可扫描：app/sidecar/requirements.txt 里每个包用 pip-licenses --fail-on 拒 GPL/LGPL/AGPL；
认不出许可（UNKNOWN）也算失败。--selftest：用 --fail-on MIT 对 pytest（MIT）跑一遍，确认机制真会失败。
没装 pip-licenses 直接失败（pip install -r app/sidecar/requirements.txt），不跳过。"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FAIL_ON = "GPL;General Public License;UNKNOWN"


def packages() -> list[str]:
    out = []
    for line in (ROOT / "app/sidecar/requirements.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Za-z0-9_.\-]+)", line.split("#")[0])
        if m:
            out.append(m.group(1))
    return out


def run(pkgs, fail_on) -> int:
    cmd = [sys.executable, "-m", "piplicenses", "--partial-match", f"--fail-on={fail_on}", "--packages", *pkgs]
    try:
        return subprocess.run(cmd, capture_output=True, text=True).returncode
    except FileNotFoundError:
        return 127


def main() -> int:
    if subprocess.run([sys.executable, "-m", "piplicenses", "--version"], capture_output=True).returncode:
        print("✗ [licenses/pip] 检查没跑成 · 原因：没装 pip-licenses · 处理：pip install -r app/sidecar/requirements.txt")
        return 1
    if "--selftest" in sys.argv:
        ok = run(["pytest"], "MIT") != 0 and run(["pytest"], FAIL_ON) == 0
        print("check_py_licenses 自测:", "通过" if ok else "失败（--fail-on 没生效）")
        return 0 if ok else 1
    pk = packages()
    rc = run(pk, FAIL_ON)
    if rc:
        print("✗ [licenses/pip] 有依赖是 GPL/LGPL/AGPL 或许可不明 · 原因：会把传染义务带进侧车发行包 · 处理：见下表，换成 MIT/BSD/Apache 的同类包")
        subprocess.run([sys.executable, "-m", "piplicenses", "--partial-match", "--packages", *pk])
    print(f"check_py_licenses（{len(pk)} 个包，拒 GPL/LGPL/AGPL/UNKNOWN）:", "失败" if rc else "通过")
    return 1 if rc else 0


if __name__ == "__main__":
    sys.exit(main())
