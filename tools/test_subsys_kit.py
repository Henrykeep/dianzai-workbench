#!/usr/bin/env python3
"""子系统搬家回归：声明不过期；ball 单独装进新题目能生成+编译（ball.c 一字不改）；拿掉 chassis 后原题目照常编译。"""
import filecmp
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import subsys_kit  # noqa: E402

fails = []


def ok(cond, msg):
    print(("✓ " if cond else "✗ ") + msg)
    if not cond:
        fails.append(msg)


def build(app_dir: pathlib.Path) -> bool:
    if not shutil.which("cc") or not shutil.which("make"):
        print("  （没有 cc/make，跳过编译）")
        return True
    r = subprocess.run(["make", "-s", "BOARD=host-sim", f"APP={app_dir.name}", f"APP_DIR={app_dir}",
                        f"OUT={app_dir}/_build"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-1500:], r.stderr[-1500:])
    return r.returncode == 0


def gen_check(app_dir: pathlib.Path) -> bool:
    return subprocess.run([sys.executable, "tools/gen_project.py", str(app_dir / "project.yaml"), "--check"],
                          cwd=ROOT, capture_output=True).returncode == 0


H = ROOT / "examples" / "2026H_ball"
for sd in sorted((H / "subsys").iterdir()):
    if sd.is_dir() and not sd.name.startswith("."):
        f = sd / "subsys.yaml"
        ok(f.exists() and f.read_text(encoding="utf-8") == subsys_kit.write_manifest(sd, write=False),
           f"{sd.name}/subsys.yaml 与代码一致（不一致就跑 python3 tools/subsys_kit.py manifest {sd.relative_to(ROOT)}）")

with tempfile.TemporaryDirectory() as t:
    dst = pathlib.Path(t) / "ball_only"
    subsys_kit.add(H / "subsys" / "ball", dst, "host-sim")
    ok(not filecmp.dircmp(H / "subsys" / "ball", dst / "subsys" / "ball").diff_files, "ball 原样复制（代码没改）")
    ok(gen_check(dst), "ball 单独装进新题目：project.yaml 通过 gen_project --check")
    ok(build(dst), "ball 单独装进新题目：host-sim 编译通过")
    subsys_kit.add(H / "subsys" / "chassis", dst, "host-sim")
    ok(gen_check(dst) and build(dst), "再装 chassis：chassis_out 写者 io → chassis，仍能生成+编译")

    cp = pathlib.Path(t) / "rm"
    shutil.copytree(H, cp)
    subsys_kit.remove(cp, "chassis")
    ok(not (cp / "subsys" / "chassis").exists() and any((cp / "subsys" / ".removed").iterdir()), "chassis 代码挪到 .removed（没删）")
    ok(gen_check(cp) and build(cp), "拿掉 chassis 后原题目仍能生成+编译（io_main.c 不用改）")

print("test_subsys_kit: " + ("失败 " + str(len(fails)) if fails else "通过"))
sys.exit(1 if fails else 0)
