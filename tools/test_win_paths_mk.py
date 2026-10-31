#!/usr/bin/env python3
"""回归：Windows 绝对路径（C:/...）的源文件不能把 ':' 带进 make 目标名（74c90fd Windows CI：Makefile:173 multiple target patterns）。
从 Makefile 抽出 obj_of / hal_obj_of / HAL_OBJS 定义，喂入 C:/ 路径，检查生成的目标里除首行外没有 ':'。"""
import re, subprocess, sys, tempfile, os
mk = open(os.path.join(os.path.dirname(__file__), "..", "Makefile"), encoding="utf-8").read()
defs = [l for l in mk.splitlines() if re.match(r"^(obj_of|hal_obj_of|HAL_OBJS|OBJS|DRV_SRCS|HAL_DRV_SRCS) *=", l)]
assert any(l.startswith("hal_obj_of") for l in defs), "Makefile 缺 hal_obj_of"
stub = "OUT := build/t6car\nSRCS := app/a.c C:/Car/Core/Src/main.c\nHAL_SRC := C:/Car/Drivers/hal.c D:/x/y.c\nSTARTUP := C:/Car/startup.s\n" + "\n".join(defs) + "\n$(info OBJS=$(OBJS))\n$(info HAL=$(HAL_OBJS))\n$(info HD=$(HAL_DRV_SRCS))\nall:;@:\n"
with tempfile.NamedTemporaryFile("w", suffix=".mk", delete=False) as f: f.write(stub)
out = subprocess.run(["make", "-s", "-f", f.name], capture_output=True, text=True); os.unlink(f.name)
assert out.returncode == 0, out.stderr
v = dict(l.split("=", 1) for l in out.stdout.splitlines())
objs = (v["OBJS"] + " " + v["HAL"]).split()
bad = [o for o in objs if ":" in o]
assert not bad, f"目标名含 ':'：{bad}"
assert len(v["HAL"].split()) == 3 and len(v["HD"].split()) == 3, v
print("✓ Windows 盘符路径不进目标名：", len(objs), "个目标")
