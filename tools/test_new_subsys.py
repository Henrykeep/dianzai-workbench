#!/usr/bin/env python3
"""new_subsys.py 端到端：在示例题目的副本里生成子系统 → 按它打印的片段加进 project.yaml → gen_project 通过 →
生成的 .c 能编译；再跑一次不覆盖已有文件。"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PY = sys.executable


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td) / "2026H_ball"
        shutil.copytree(ROOT / "examples/2026H_ball", proj)
        r = subprocess.run([PY, ROOT / "tools/new_subsys.py", proj, "gimbal", "--owns", "gimbal_out", "--reads", "vision_out",
                            "--period", "5"], capture_output=True, text=True, check=True)
        c = proj / "subsys/gimbal/gimbal.c"
        assert c.exists() and (proj / "tests/test_gimbal.c").exists() and "subsystems:" in r.stdout, r.stdout
        y = (proj / "project.yaml").read_text(encoding="utf-8")
        entry = next(ln for ln in r.stdout.splitlines() if ln.strip().startswith("- { name: gimbal"))
        y = y.replace("subsystems:\n", "subsystems:\n" + entry.replace("    - ", "  - ", 1) + "\n", 1)
        y = y.replace("\nstate:\n", "\nstate:\n  gimbal_out:\n    owner: gimbal\n    fields:\n      - { name: cmd, type: float }\n", 1)
        (proj / "project.yaml").write_text(y, encoding="utf-8")
        gen = pathlib.Path(td) / "gen"
        subprocess.run([PY, ROOT / "tools/gen_project.py", proj / "project.yaml", "-o", gen], check=True, capture_output=True)
        dirs = [gen, ROOT / "firmware/common", *[d for d in (ROOT / "firmware/framework").rglob("*") if d.is_dir()],
                ROOT / "firmware/framework"]
        inc = [x for d in dirs for x in ("-I", d)]
        cc = subprocess.run(["cc", "-std=c11", "-fsyntax-only", "-Wall", *map(str, inc), str(c)], capture_output=True, text=True)
        assert cc.returncode == 0, cc.stderr[-1500:]
        c.write_text("// 用户改过\n", encoding="utf-8")
        r2 = subprocess.run([PY, ROOT / "tools/new_subsys.py", proj, "gimbal"], capture_output=True, text=True, check=True)
        assert "跳过" in r2.stdout and c.read_text(encoding="utf-8") == "// 用户改过\n", "不能覆盖已有文件"
    print("new_subsys 端到端通过")


if __name__ == "__main__":
    main()
