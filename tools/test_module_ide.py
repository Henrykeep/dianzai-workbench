#!/usr/bin/env python3
"""每个固件模块（firmware/{algo,drivers,framework,proto}/*）都能被 IDE 工程生成器加进去 —— 一个模块一条检查。

Keil（tools/keil_inject.py）：在真实 .uvprojx 副本上只注入“该模块 + 它 #include 到的其它模块”（依赖按头文件名自动求闭包），
  检查：每个 .c 都进了 dz/<模块> 组、组名不重名、包含路径齐全；再用 gcc -fsyntax-only 只带这些包含路径（+ host-sim 的 board_gen.h）
  编译该模块每个 .c —— 证明“在 Keil 里勾这个模块就够了”，不会漏头文件。
CCS（tools/gen_ccs_projectspec.py）：生成的 .projectspec 里每个模块的每个 .c 都以 link 方式出现、模块目录在 -I 里。
【已实测】本机 python + gcc；Keil/CCS 本体未打开。
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import keil_inject  # noqa: E402

MODS = sorted(p for k in ("algo", "drivers", "framework", "proto") for p in (ROOT / "firmware" / k).iterdir() if p.is_dir())
HDR = {h.name: m for m in MODS for h in m.glob("*.h")}
BASE_INC = [ROOT / "firmware/common", ROOT / "firmware/pal"]
SIM_GEN = ROOT / "build/host-sim/gen"


def deps(m: pathlib.Path) -> list[pathlib.Path]:
    """模块 m 的依赖闭包（含自身），按 #include "x.h" 对上其它模块的头文件。"""
    out, todo = [], [m]
    while todo:
        d = todo.pop()
        if d in out:
            continue
        out.append(d)
        for f in list(d.glob("*.c")) + list(d.glob("*.h")):
            for h in re.findall(r'#include\s+"([^"]+)"', f.read_text(encoding="utf-8", errors="replace")):
                if h in HDR and HDR[h] not in out:
                    todo.append(HDR[h])
    return out


def check_keil(uv_src: pathlib.Path) -> int:
    fail = 0
    for m in MODS:
        need = deps(m)
        with tempfile.TemporaryDirectory() as t:
            uv = pathlib.Path(t) / "MDK-ARM" / uv_src.name
            uv.parent.mkdir()
            shutil.copy(uv_src, uv)
            rel = [str(d.relative_to(ROOT)) for d in need]
            groups, incs = keil_inject.plan(uv, ROOT, rel, [], [])
            text = keil_inject.inject(uv.read_text(encoding="utf-8"), groups, incs, [])
            names = re.findall(r"<GroupName>(dz/[^<]*)</GroupName>", text)
            per_target = len(names) // max(1, text.count("<Target>"))
            srcs_ok = all(f"<FilePath>{keil_inject.rel(c, uv.parent)}</FilePath>" in text for d in need for c in d.glob("*.c"))
            groups_ok = per_target == len(need) == len(set(names[:per_target]))
            # 只用 Keil 会得到的包含路径编译（host-sim 的 board_gen.h 代替 CubeMX/板卡生成头）
            inc_args = [f"-I{(uv.parent / i.replace(chr(92), '/')).resolve()}" for i in incs] + [f"-I{SIM_GEN}"]
            cc_ok, err = True, ""
            for c in m.glob("*.c"):
                r = subprocess.run(["gcc", "-std=c11", "-fsyntax-only", "-Wall", *inc_args, str(c)], capture_output=True, text=True)
                if r.returncode:
                    cc_ok, err = False, r.stderr.strip().splitlines()[0] if r.stderr.strip() else "?"
            ok = srcs_ok and groups_ok and cc_ok
            dep_s = ",".join(d.name for d in need[1:]) or "-"
            print(f"{'✓' if ok else '✗'} keil {m.parent.name}/{m.name}（依赖 {dep_s}）{'' if ok else f' src={srcs_ok} grp={groups_ok} cc={err}'}")
            fail += not ok
    return fail


def check_ccs(board: str, app: str) -> int:
    path, text = __import__("gen_ccs_projectspec").render(board, app)
    fail = 0
    for m in MODS:
        rel = lambda p: __import__("os").path.relpath(p, path.parent).replace("\\", "/")
        srcs_ok = all(f'path="{rel(c)}"' in text for c in m.glob("*.c"))
        inc_ok = f"-I${{PROJECT_LOC}}/{rel(m)}" in text
        ok = srcs_ok and inc_ok
        print(f"{'✓' if ok else '✗'} ccs  {board} {m.parent.name}/{m.name}{'' if ok else f' src={srcs_ok} inc={inc_ok}'}")
        fail += not ok
    return fail


def main() -> int:
    subprocess.run(["make", "-s", "BOARD=host-sim", "APP=car_2wd", "gen"], cwd=ROOT, check=True, capture_output=True)  # 每次都跑（增量）：不用本机残留的旧 gen
    uv = sorted((ROOT / "tools/testdata/real").glob("*.uvprojx"))[0]
    fail = check_keil(uv)
    for b in ("mspm0g3507-tianmengxing", "mspm0g3507-launchpad"):
        fail += check_ccs(b, "car_2wd")
    print(f"{'✗' if fail else '✓'} 模块 × IDE：{len(MODS)} 个模块，失败 {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
