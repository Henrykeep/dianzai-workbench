#!/usr/bin/env python3
"""对用户两个真实 .uvprojx 的副本注入两次：第二次不应有变化；XML 合法；原有组/宏/包含路径都保留。"""
import pathlib, re, shutil, subprocess, sys, tempfile, xml.dom.minidom
ROOT = pathlib.Path(__file__).resolve().parent.parent
MODS = ["firmware/algo/pid", "firmware/drivers/motor_dc", "firmware/proto/dzframe", "ports/stm32-cubemx"]
fail = 0
for src in sorted((ROOT / "tools/testdata/real").glob("*.uvprojx")):
    with tempfile.TemporaryDirectory() as t:
        f = pathlib.Path(t) / "MDK-ARM" / src.name
        f.parent.mkdir()
        shutil.copy(src, f)
        args = [sys.executable, str(ROOT / "tools/keil_inject.py"), str(f), "--root", str(ROOT), "--define", "DZ_TEST"]
        for m in MODS + ["apps/include"]:
            args += ["--module", m] if m != "apps/include" else ["--extra-inc", m]
        subprocess.run(args, check=True, capture_output=True)
        once = f.read_text(encoding="utf-8")
        subprocess.run(args, check=True, capture_output=True)
        twice = f.read_text(encoding="utf-8")
        orig = src.read_text(encoding="utf-8")
        xml.dom.minidom.parseString(twice.encode())
        old_groups = re.findall(r"<GroupName>([^<]*)</GroupName>", orig)
        new_groups = re.findall(r"<GroupName>([^<]*)</GroupName>", twice)
        ok = once == twice and all(g in new_groups for g in old_groups) and "DZ_TEST" in twice \
            and sum(g.startswith("dz/") for g in new_groups) == len(MODS) * orig.count("<Target>")
        print(("✓" if ok else "✗"), src.name, f"原有组 {len(old_groups)}，新增 {len(new_groups) - len(old_groups)}")
        fail += not ok
sys.exit(1 if fail else 0)
