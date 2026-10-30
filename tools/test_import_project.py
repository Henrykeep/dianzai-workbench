#!/usr/bin/env python3
"""回归：用户原样的两个工程（p2 Car_Mode1021 / F103，p1 Bldc / F407 FreeRTOS，Keil 生成、没有 .ld）
导入后“还需要人做的事”的条数不许比基线多（tools/testdata/real/import_baseline.json）。
还查：原工程一个字节没变；main.c 标记坏了不加 --accept-repair 会停（rc 3）且不留半成品；
用户代码一行没丢（搬进 user_code/）。有 arm-none-eabi-gcc 和 HAL 时再真编译，否则跳过编译。"""
import filecmp
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "tools" / "testdata" / "real" / "projects"
BASE = json.loads((ROOT / "tools" / "testdata" / "real" / "import_baseline.json").read_text(encoding="utf-8"))
fails = []


def ok(c, m):
    print(("✓ " if c else "✗ ") + m)
    if not c:
        fails.append(m)


def tree_hash(d: pathlib.Path) -> str:
    h = hashlib.sha256()
    for f in sorted(d.rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(d)).encode()); h.update(f.read_bytes())
    return h.hexdigest()


BOARDS = pathlib.Path(tempfile.mkdtemp(prefix="dz-import-boards-"))
import atexit  # noqa: E402
import signal  # noqa: E402
atexit.register(shutil.rmtree, BOARDS, True)  # 正常退出/异常都清临时板根
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # 被 kill（TERM）也走 atexit 清理
os.environ["DZ_BOARDS_DIR"] = str(BOARDS)  # subsys_kit 等按名找板时也看这里   # 导入的板放临时目录：中途被杀也不在仓库 boards/ 留 zz-test-*


def imp(src, name, *args):
    return subprocess.run([sys.executable, "tools/import_project.py", str(src), "--name", name, "--boards-dir", str(BOARDS), *args],
                          cwd=ROOT, capture_output=True, text=True)


has_arm = shutil.which("arm-none-eabi-gcc") is not None
for proj, exp in BASE.items():
    if proj.startswith("_"):
        continue
    src = DATA / proj
    name = "zz-test-" + str(abs(hash(proj)) % 10000)
    dest = BOARDS / name
    before = tree_hash(src)
    try:
        if "--accept-repair" in exp["args"]:
            r = imp(src, name, *[a for a in exp["args"] if a != "--accept-repair"])
            ok(r.returncode == 3 and not dest.exists(), f"{proj}：USER CODE 标记坏了 → 不加 --accept-repair 就停（rc {r.returncode}），不留半成品")
        with tempfile.TemporaryDirectory() as t:
            rep = pathlib.Path(t) / "r.json"
            r = imp(src, name, *exp["args"], "--report", str(rep))
            ok(r.returncode == 0 and rep.exists(), f"{proj}：导入成功（rc {r.returncode}）")
            if r.returncode or not rep.exists():
                print(r.stdout[-2000:], r.stderr[-2000:])
                continue
            d = json.loads(rep.read_text(encoding="utf-8"))
        cnt = {k: sum(1 for x in d["todo"] if x["kind"] == k) for k in ("edit", "confirm", "observe")}
        for k, v in cnt.items():
            ok(v <= exp[k], f"{proj}：{k} {v} 处（基线 ≤ {exp[k]}）")
            if v < exp[k]:
                print(f"  ↓ 比基线少了，把 import_baseline.json 里 {proj}.{k} 改成 {v}")
        ok(tree_hash(src) == before, f"{proj}：原工程没被改动")
        moved = (dest / "user_code" / "from_core_user_code.c.txt").read_bytes() if (dest / "user_code" / "from_core_user_code.c.txt").exists() else b""
        orig_main = (src / "Core" / "Src" / "main.c").read_bytes()
        # 用户在 main.c 里写过的每一行非空代码，要么还在新 main.c，要么在 user_code/ 里
        new_main = (dest / "cubemx" / "Core" / "Src" / "main.c").read_bytes()
        lost = [l for l in orig_main.splitlines() if l.strip() and l.strip() not in new_main and l.strip() not in moved]
        ok(not lost, f"{proj}：main.c 里的用户代码一行没丢（丢了 {len(lost)} 行）")
        if lost:
            print("  ", lost[:5])
        # 新题目装进 ball + chassis，板子就是刚导入的这块：io 层自动接线，剩多少 TODO/确认
        io = exp.get("io")
        if io:
            sys.path.insert(0, str(ROOT / "tools"))
            import subsys_kit
            with tempfile.TemporaryDirectory() as t2:
                pd = pathlib.Path(t2) / "io_try"
                for sname in io["subsys"]:
                    subsys_kit.add(ROOT / "examples" / "2026H_ball" / "subsys" / sname, pd, name)
                r = dict(subsys_kit.LAST_IO)
                ok(len(r["todo"]) <= io["todo"], f"{proj}：io 自动接线 {r['binds']} 个字段，TODO {len(r['todo'])} 处（基线 ≤ {io['todo']}）")
                ok(len(r["confirm"]) <= io["confirm"], f"{proj}：io 确认 {len(r['confirm'])} 处（基线 ≤ {io['confirm']}）")
                for x in r["todo"]:
                    print("    TODO", x)
                if has_arm:
                    b = subprocess.run(["make", "-s", f"BOARDS_DIR={BOARDS}", f"BDIR={BOARDS}/_build/{name}/io_try", f"BOARD={name}", f"APP=io_try", f"APP_DIR={pd}", f"OUT={pd}/_build"],
                                       cwd=ROOT, capture_output=True, text=True)
                    if b.returncode and "找不到" in b.stdout + b.stderr:
                        print("  （缺器件包，跳过 io_try 编译）")
                    else:
                        ok(b.returncode == 0, f"{proj}：自动生成 io 的新题目在这块板上编译通过")
                        if b.returncode:
                            print(b.stdout[-1500:], b.stderr[-1500:])
        if has_arm:
            for app in exp["build"]:
                b = subprocess.run(["make", "-s", f"BOARDS_DIR={BOARDS}", f"BDIR={BOARDS}/_build/{name}/{app}", f"BOARD={name}", f"APP={app}"], cwd=ROOT, capture_output=True, text=True)
                skip = b.returncode and "找不到" in b.stdout + b.stderr   # 没有 HAL/FreeRTOS 等器件包：跳过，不算失败
                if skip:
                    print(f"  （缺器件包（HAL/FreeRTOS），跳过 {app} 编译）"); break
                ok(b.returncode == 0, f"{proj}：make APP={app} 编译通过")
                if b.returncode:
                    print(b.stdout[-1500:], b.stderr[-1500:])
        else:
            print("  （没有 arm-none-eabi-gcc，跳过编译）")
    finally:
        shutil.rmtree(dest, ignore_errors=True)

shutil.rmtree(BOARDS, ignore_errors=True)

print("test_import_project: " + ("失败 " + str(len(fails)) if fails else "通过"))
sys.exit(1 if fails else 0)
