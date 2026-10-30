#!/usr/bin/env python3
"""gen_syscfg 时钟规则自测：用了 DAC12 就自动打开 SYSCTL.MFPCLKEn（SysConfig 硬约束），没用就不写；入库的 .syscfg 也守同一条规则。不需要 SysConfig CLI。"""
import pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import gen_syscfg  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ok = True
def chk(name, cond):
    global ok; ok &= bool(cond); print(f"{'✓' if cond else '✗'} {name}")

dac = {"dac": [{"name": "OUT", "instance": "DAC0", "channel": 0, "pin": "PA15"}]}
s = gen_syscfg.script(dac, {}, [])
chk("有 DAC：生成 DAC12 模块", '/ti/driverlib/DAC12' in s)
chk("有 DAC：SYSCTL.MFPCLKEn = true", re.search(r"^SYSCTL\.MFPCLKEn\s*=\s*true;", s, re.M))
s = gen_syscfg.script({"uart": [{"name": "DBG", "baud": 115200}]}, {}, [])
chk("无 DAC：不写 DAC12 / MFPCLKEn", "DAC12" not in s and "MFPCLKEn" not in s)
for f in sorted(ROOT.glob("boards/*/ccs/*.syscfg")):
    t = f.read_text(encoding="utf-8")
    if "/ti/driverlib/DAC12" in t:
        chk(f"{f.relative_to(ROOT)}：用 DAC12 且开了 MFPCLK", re.search(r"^SYSCTL\.MFPCLKEn\s*=\s*true;", t, re.M))
sys.exit(0 if ok else 1)
