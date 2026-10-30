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
# --board/--app：按构建自动挑模块（头文件依赖闭包）；用的模块在、没用的（如 LINK=uart 时的 dzrtt）不在
sys.path.insert(0, str(ROOT / "tools"))
import keil_inject  # noqa: E402
mods, xs, xi, _ = keil_inject.from_build(ROOT, "stm32f103c8t6-car-cubemx", "car_2wd")
ok = {"firmware/proto/dzframe", "firmware/proto/dzctl", "firmware/algo/pid", "ports/stm32-cubemx"} <= set(mods) \
    and "firmware/proto/dzrtt" not in mods and "apps/car_2wd/app_main.c" in xs and any(i.endswith("linkgen") for i in xi)
print(("✓" if ok else "✗"), "--board/--app 自动挑模块：", " ".join(pathlib.Path(m).name for m in mods))
fail += not ok
# Windows 跨盘符：os.path.relpath 抛 ValueError（"path is on mount 'D:'"）→ 退回正斜杠绝对路径，而不是整个注入失败
sys.path.insert(0, str(ROOT / "tools"))
import keil_inject  # noqa: E402
_orig = keil_inject.os.path.relpath
def _cross_drive(*a, **k):
    raise ValueError("path is on mount 'D:', start on mount 'C:'")
keil_inject.os.path.relpath = _cross_drive
try:
    got = keil_inject.rel(ROOT / "firmware/algo/pid/pid.c", pathlib.Path(tempfile.gettempdir()))
finally:
    keil_inject.os.path.relpath = _orig
ok = got == (ROOT / "firmware/algo/pid/pid.c").resolve().as_posix() and "\\" not in got
print(("✓" if ok else "✗"), "跨盘符 relpath 失败退回绝对路径：", got)
fail += not ok
ok = keil_inject.rel(ROOT / "a/b.c", ROOT / "x") == "..\\a\\b.c"
print(("✓" if ok else "✗"), "同盘仍写相对路径（反斜杠）")
fail += not ok
sys.exit(1 if fail else 0)
