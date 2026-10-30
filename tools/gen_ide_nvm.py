#!/usr/bin/env python3
"""gen_ide_nvm.py —— 按 board.yaml mcu.nvm_kb 给 Keil / CCS 工程生成“让出掉电保存区”的链接文件。

Keil（stm32-cubemx 板）→ boards/<板>/keil/dz_nvm.sct（armlink 分散加载文件）：
  F1：程序区 = Flash 去掉末尾 nvm_kb；保存区单独一个加载域里的 EMPTY 执行域 ER_DZ_NVM（不进 hex，下载不会擦它）。
  F4：扇区 0 只放向量表（LR_VEC），扇区 1.. 是 ER_DZ_NVM，程序从 0x08004000+nvm 开始（与 make 的链接脚本同布局）。
  keil_inject.py --board 会把这个文件填进 Options→Linker→Scatter File，关掉“Use Memory Layout from Target Dialog”，
  再加 DZ_NVM_KB/DZ_FLASH_KB 宏。pal_cubemx.c 在 armclang 下核对 Image$$ER_DZ_NVM$$ZI$$Base == 保存区起点。
CCS（mspm0-driverlib 板）→ boards/<板>/ccs/dz_nvm_linker.cmd：TI SDK ticlang/mspm0g3507.cmd 把 FLASH 长度减 nvm_kb，
  另加符号 __dz_nvm_base；.syscfg 里要 ProjectConfig.genLinker = false（不让 SysConfig 再生成一份）。
  gen_ccs_projectspec.py 把这个 .cmd 和宏加进 projectspec。pal_mspm0.c 在 tiarmclang 下核对 __dz_nvm_base。
【未测】Keil / CCS 里没编译过（本机无 armclang / tiarmclang）；生成内容由 tools/test_ide_nvm.py 核对地址算法与 pal 一致。

用法：gen_ide_nvm.py            写全部 nvm_kb>0 的板
      gen_ide_nvm.py --check    只比对（make check）
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import boardlib  # noqa: E402

TI_CMD = ROOT / "third_party/mspm0-sdk/source/ti/devices/msp/m0p/linker_files/ticlang/mspm0g3507.cmd"
HDR = "由 tools/gen_ide_nvm.py 按 board.yaml mcu.nvm_kb={nvm} 生成，勿手改。【未测】未在 {ide} 里编译过。"


def layout(mcu: dict) -> dict:
    """与 pal_cubemx.c / pal_mspm0.c 的 NVM_BASE 同一算法。"""
    fam, fk, nk = mcu["family"], int(mcu["flash_kb"]), int(mcu.get("nvm_kb", 0) or 0)
    if fam == "stm32f4":
        if nk not in (32, 48):
            raise SystemExit(f"✗ stm32f4 nvm_kb 只能 32/48（扇区 1..2 / 1..3），现在 {nk}")
        return dict(flash=0x08000000, flash_size=fk * 1024, nvm=0x08004000, nvm_size=nk * 1024,
                    ram=0x20000000, ram_size=min(int(mcu.get("ram_kb", 128)), 128) * 1024)
    if fam == "stm32f1":
        return dict(flash=0x08000000, flash_size=fk * 1024, nvm=0x08000000 + (fk - nk) * 1024, nvm_size=nk * 1024,
                    ram=0x20000000, ram_size=int(mcu.get("ram_kb", 20)) * 1024)
    if fam.startswith("mspm0"):
        return dict(flash=0, flash_size=fk * 1024, nvm=(fk - nk) * 1024, nvm_size=nk * 1024,
                    ram=0x20200000, ram_size=int(mcu.get("ram_kb", 32)) * 1024)
    raise SystemExit(f"✗ {fam}：没有 IDE 保存区布局")


def keil_sct(mcu: dict) -> str:
    L = layout(mcu)
    h = lambda x: f"0x{x:08X}"
    head = f"; {HDR.format(nvm=mcu['nvm_kb'], ide='Keil')}\n; 保存区 ER_DZ_NVM {h(L['nvm'])} 长 {h(L['nvm_size'])}：EMPTY 域，不进 hex/axf 的加载数据，下载不会擦掉已存参数。\n"
    nvm = f"LR_DZ_NVM {h(L['nvm'])} {h(L['nvm_size'])} {{\n  ER_DZ_NVM {h(L['nvm'])} EMPTY {h(L['nvm_size'])} {{ }}\n}}\n"
    ram = f"  RW_IRAM1 {h(L['ram'])} {h(L['ram_size'])} {{\n   .ANY (+RW +ZI)\n  }}\n"
    if mcu["family"] == "stm32f4":
        start = L["nvm"] + L["nvm_size"]
        size = L["flash"] + L["flash_size"] - start
        return head + (f"LR_VEC {h(L['flash'])} 0x00004000 {{\n  ER_VEC {h(L['flash'])} 0x00004000 {{\n   *.o (RESET, +First)\n  }}\n}}\n"
                       + nvm + f"LR_IROM1 {h(start)} {h(size)} {{\n  ER_IROM1 {h(start)} {h(size)} {{\n"
                       "   *(InRoot$$Sections)\n   .ANY (+RO)\n   .ANY (+XO)\n  }\n" + ram + "}\n")
    size = L["nvm"] - L["flash"]
    return head + (f"LR_IROM1 {h(L['flash'])} {h(size)} {{\n  ER_IROM1 {h(L['flash'])} {h(size)} {{\n"
                   "   *.o (RESET, +First)\n   *(InRoot$$Sections)\n   .ANY (+RO)\n   .ANY (+XO)\n  }\n" + ram + "}\n" + nvm)


def ccs_cmd(mcu: dict) -> str:
    L = layout(mcu)
    t = TI_CMD.read_text(encoding="utf-8")
    old = "FLASH           (RX)  : origin = 0x00000000, length = 0x00020000"
    if old not in t or L["flash_size"] != 0x20000:
        raise SystemExit("✗ TI 模板 FLASH 行变了或不是 128 KB 片子：更新 gen_ide_nvm.py")
    t = t.replace(old, f"FLASH           (RX)  : origin = 0x00000000, length = 0x{L['nvm']:08X}   /* 原 0x00020000，末尾 {mcu['nvm_kb']} KB 给 DZ_NVM */\n"
                       f"    DZ_NVM          (R)   : origin = 0x{L['nvm']:08X}, length = 0x{L['nvm_size']:08X}")
    t = t.replace("\nSECTIONS", f"\n__dz_nvm_base = 0x{L['nvm']:08X};   /* pal_mspm0.c 核对：用的是这份 .cmd */\n\nSECTIONS", 1)
    return (f"/* {HDR.format(nvm=mcu['nvm_kb'], ide='CCS')}\n * Source: MSPM0 SDK source/ti/devices/msp/m0p/linker_files/ticlang/mspm0g3507.cmd（TI BSD-3，版权声明保留如下）；\n"
            " * 改动：FLASH 去掉末尾保存区、加 DZ_NVM 区与 __dz_nvm_base 符号。用它时 .syscfg 要 ProjectConfig.genLinker = false。 */\n" + t)


def targets():
    for by in sorted((ROOT / "boards").glob("*/board.yaml")):
        b = boardlib.load_board(by)
        mcu = b.get("mcu", {})
        if not int(mcu.get("nvm_kb", 0) or 0):
            continue
        if b.get("port") == "stm32-cubemx":
            yield by.parent / "keil" / "dz_nvm.sct", keil_sct(mcu)
        elif b.get("port") == "mspm0-driverlib":
            if not TI_CMD.exists():   # 没拉 MSPM0 SDK（preflight / CI 无器件包）：CCS .cmd 没法比对，跳过而不是崩
                print(f"- 跳过 {by.parent.name}：缺 {TI_CMD.relative_to(ROOT)}（bash tools/fetch_third_party.sh 拉 SDK 后再查）")
                continue
            yield by.parent / "ccs" / "dz_nvm_linker.cmd", ccs_cmd(mcu)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    bad = 0
    for p, text in targets():
        if a.check:
            ok = p.exists() and p.read_text(encoding="utf-8") == text
            bad += not ok
            print(f"{'✓' if ok else '✗'} {p.relative_to(ROOT)}{'' if ok else ' 过期：重跑 tools/gen_ide_nvm.py'}")
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            print(f"写入 {p.relative_to(ROOT)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
