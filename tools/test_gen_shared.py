#!/usr/bin/env python3
"""gen/ 按板共享：换应用 / 新建工程（app.yaml 更新）不得重写 board_gen.h（否则同板所有应用整套重编，
仿真板 connect 一次 20–60 s，负载下把调参用例拖过 120 s，表现为卡在 step_wait）。内容不变时 gen_board 不重写。"""
import os, pathlib, shutil, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
PY = sys.executable


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        t = pathlib.Path(td)
        bdir = t / "build"
        apps = []
        for name in ("a1", "a2"):
            d = t / name
            shutil.copytree(ROOT / "apps" / "motor_pos", d)
            apps.append(d)
        def gen(app: pathlib.Path) -> None:
            subprocess.run(["make", "-s", f"BDIR={bdir}", "BOARD=host-sim", f"APP={app.name}", f"APP_DIR={app}", "gen"],
                           cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        gen(apps[0])
        h = bdir / "gen" / "board_gen.h"
        m0 = h.stat().st_mtime_ns
        time.sleep(0.05)
        (apps[1] / "app.yaml").touch()               # 另一个（新建的）工程：app.yaml 比 gen/ 新
        gen(apps[1])
        assert h.stat().st_mtime_ns == m0, "换应用重写了共享的 board_gen.h（同板其它应用会整套重编）"
        # gen_board 本身：内容不变不重写
        subprocess.run([PY, "tools/gen_board.py", "boards/host-sim/board.yaml", "-o", str(bdir / "gen")], cwd=ROOT, check=True,
                       stdout=subprocess.DEVNULL)
        assert h.stat().st_mtime_ns == m0, "gen_board.py 内容没变也重写了 board_gen.h"
    print("✓ gen/ 共享：换应用 / 重跑生成器不重写 board_gen.h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
