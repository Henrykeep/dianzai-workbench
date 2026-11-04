#!/usr/bin/env python3
"""第 4.4 步 外设配置代码生成：无界面调用厂家工具，不用人点「生成」。

  python3 tools/gen_config.py cubemx    <x.ioc>     -o out/ [--json]   # STM32CubeMX -q 脚本：config load / project generate
  python3 tools/gen_config.py sysconfig <x.syscfg>  -o out/ [--json] [--sdk third_party/mspm0-sdk]   # TI sysconfig_cli

找工具：CubeMX 用环境变量 STM32CUBEMX，再找 PATH 里 STM32CubeMX(.exe)、常见安装目录；
SysConfig 用 SYSCFG_CLI，再找 third_party/sysconfig_*/、~/ti/sysconfig_*/、C:/ti/sysconfig_*/ 里的 sysconfig_cli.(sh|bat)。
退出码：0 成功 / 1 工具报错或没生成文件 / 2 参数错 / 3 缺工具或 SDK / 10+ 内部错误。"""
from __future__ import annotations

import argparse
import glob
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
WIN = os.name == "nt"


def find_cubemx() -> str | None:
    for c in [os.environ.get("STM32CUBEMX"), shutil.which("STM32CubeMX"), shutil.which("STM32CubeMX.exe"),
              *glob.glob(os.path.expanduser("~/STM32CubeMX/STM32CubeMX")), *glob.glob("C:/Program Files/STMicroelectronics/STM32Cube/STM32CubeMX/STM32CubeMX.exe"),
              *glob.glob("/opt/st/stm32cubemx*/STM32CubeMX")]:
        if c and pathlib.Path(c).is_file():
            return c
    return None


def find_sysconfig() -> str | None:
    name = "sysconfig_cli.bat" if WIN else "sysconfig_cli.sh"
    cands = [os.environ.get("SYSCFG_CLI")] + sorted(glob.glob(str(ROOT / "third_party/sysconfig_*" / name)), reverse=True) \
        + sorted(glob.glob(os.path.expanduser(f"~/ti/sysconfig_*/{name}")), reverse=True) + sorted(glob.glob(f"C:/ti/sysconfig_*/{name}"), reverse=True)
    return next((c for c in cands if c and pathlib.Path(c).is_file()), None)


def cubemx(ioc: pathlib.Path, out: pathlib.Path) -> tuple[int, dict]:
    exe = find_cubemx()
    if not exe:
        return 3, {"error": "找不到 STM32CubeMX：装好后设环境变量 STM32CUBEMX=<STM32CubeMX 可执行文件>，或加入 PATH"}
    out.mkdir(parents=True, exist_ok=True)
    work = out / ioc.name
    if work.resolve() != ioc.resolve():
        shutil.copy2(ioc, work)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(f"config load {work.resolve().as_posix()}\nproject generate\nexit\n")
        script = f.name
    try:
        r = subprocess.run([exe, "-q", script], capture_output=True, text=True, timeout=900)
    finally:
        os.unlink(script)
    gen = sorted(str(p) for p in out.rglob("main.c"))
    if r.returncode or not gen:
        return 1, {"error": "CubeMX 生成失败", "log": (r.stdout + r.stderr)[-1500:]}
    return 0, {"tool": exe, "out": str(out), "generated": gen}


def sysconfig(sc: pathlib.Path, out: pathlib.Path, sdk: pathlib.Path, device: str | None, package: str | None) -> tuple[int, dict]:
    cli = find_sysconfig()
    if not cli:
        return 3, {"error": "找不到 TI SysConfig CLI：make fetch（tools/fetch_sysconfig.sh）或设 SYSCFG_CLI"}
    prod = sdk / ".metadata/product.json"
    if not prod.is_file():
        return 3, {"error": f"MSPM0 SDK 缺 {prod}：tools/fetch_third_party.sh mspm0 或 --sdk 指到 SDK 根目录"}
    head = sc.read_text(encoding="utf-8", errors="replace")[:4000]
    m = re.search(r'//\s*@cliArgs\s+--device\s+"([^"]+)"\s+--package\s+"([^"]+)"', head)
    device = device or (m and m.group(1)); package = package or (m and m.group(2))
    if not device or not package:
        return 2, {"error": ".syscfg 里没有 //@cliArgs --device/--package：用 --device、--package 指定"}
    out.mkdir(parents=True, exist_ok=True)
    cmd = ([cli] if WIN else ["bash", cli]) + ["--product", str(prod), "--device", device, "--package", package, "-o", str(out), str(sc)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    gen = sorted(str(p) for p in out.glob("ti_msp_dl_config.*"))
    if r.returncode or not gen:
        return 1, {"error": "SysConfig 生成失败", "log": (r.stdout + r.stderr)[-1500:]}
    return 0, {"tool": cli, "out": str(out), "generated": gen}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tool", choices=["cubemx", "sysconfig"]); ap.add_argument("input"); ap.add_argument("-o", required=True)
    ap.add_argument("--sdk", default=str(ROOT / "third_party/mspm0-sdk")); ap.add_argument("--device"); ap.add_argument("--package")
    ap.add_argument("--json", action="store_true")
    try:
        ns = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    src = pathlib.Path(ns.input)
    if not src.is_file():
        code, pay = 2, {"error": f"输入文件不存在：{src}"}
    else:
        try:
            code, pay = cubemx(src, pathlib.Path(ns.o)) if ns.tool == "cubemx" else sysconfig(src, pathlib.Path(ns.o), pathlib.Path(ns.sdk), ns.device, ns.package)
        except subprocess.TimeoutExpired:
            code, pay = 10, {"error": "生成超时（900 s）"}
    pay = {"ok": code == 0, "exit": code, **pay}
    print(json.dumps(pay, ensure_ascii=False, indent=1) if ns.json else (("✓ 生成 " + ", ".join(pay.get("generated", []))) if code == 0 else f"✗ {pay['error']}"))
    return code


if __name__ == "__main__":
    sys.exit(main())
