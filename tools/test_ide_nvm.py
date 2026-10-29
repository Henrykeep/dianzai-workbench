#!/usr/bin/env python3
"""test_ide_nvm.py（进 make check）：Keil .sct / CCS .cmd 的掉电保存区布局与 pal 的 NVM_BASE 算法一致，
keil_inject --board 端到端把 .sct 和宏填进 .uvprojx，projectspec 带上 .cmd 与宏。【未测】armlink / tiarmclang 本机没有。"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import boardlib  # noqa: E402
import gen_ide_nvm  # noqa: E402

fails = 0


def check(ok: bool, msg: str) -> None:
    global fails
    fails += not ok
    print(f"{'✓' if ok else '✗'} {msg}")


def pal_base(mcu: dict) -> int:
    """抄 pal_cubemx.c / pal_mspm0.c 的 NVM_BASE 宏（源码里 grep 出来再算，防两边各改各的）。"""
    fk, nk = int(mcu["flash_kb"]), int(mcu["nvm_kb"])
    if mcu["family"] == "stm32f4":
        src = (ROOT / "ports/stm32-cubemx/pal_cubemx.c").read_text(encoding="utf-8")
        return int(re.search(r"#define NVM_BASE (0x[0-9A-Fa-f]+)u", src).group(1), 16)
    if mcu["family"] == "stm32f1":
        src = (ROOT / "ports/stm32-cubemx/pal_cubemx.c").read_text(encoding="utf-8")
        assert "#define NVM_BASE (0x08000000u + (DZ_FLASH_KB - DZ_NVM_KB) * 1024u)" in src
        return 0x08000000 + (fk - nk) * 1024
    src = (ROOT / "ports/mspm0-driverlib/pal_mspm0.c").read_text(encoding="utf-8")
    assert "#define NVM_BASE ((DZ_FLASH_KB - DZ_NVM_KB) * 1024u)" in src
    return (fk - nk) * 1024


def regions(sct: str) -> dict[str, tuple[int, int]]:
    return {m[0]: (int(m[1], 16), int(m[2], 16)) for m in re.findall(r"^\s*(\w+) (0x[0-9A-F]+) (?:EMPTY )?(0x[0-9A-F]+) \{", sct, re.M)}


def main() -> int:
    check(subprocess.run([sys.executable, "tools/gen_ide_nvm.py", "--check"], cwd=ROOT, capture_output=True).returncode == 0,
          "gen_ide_nvm --check：仓库里的 .sct/.cmd 是最新的")
    n = 0
    for by in sorted((ROOT / "boards").glob("*/board.yaml")):
        b = boardlib.load_board(by)
        mcu = b.get("mcu", {})
        if not int(mcu.get("nvm_kb", 0) or 0):
            continue
        n += 1
        base, size, fend = pal_base(mcu), int(mcu["nvm_kb"]) * 1024, int(mcu["flash_kb"]) * 1024
        name = by.parent.name
        if b["port"] == "stm32-cubemx":
            r = regions((by.parent / "keil/dz_nvm.sct").read_text(encoding="utf-8"))
            check(r["ER_DZ_NVM"] == (base, size), f"{name}.sct ER_DZ_NVM = pal NVM_BASE 0x{base:08X} 长 {size}")
            code = [v for k, v in r.items() if k in ("ER_VEC", "ER_IROM1")]
            check(all(s + l <= base or s >= base + size for s, l in code), f"{name}.sct 代码域不碰保存区")
            check(all(0x08000000 <= s and s + l <= 0x08000000 + fend for s, l in code), f"{name}.sct 代码域在 Flash 内")
            if mcu["family"] == "stm32f4":
                check(r["ER_VEC"] == (0x08000000, 0x4000) and r["ER_IROM1"][0] == base + size, f"{name}.sct F4：扇区 0 只放向量，程序接在保存区后")
            check("*.o (RESET, +First)" in (by.parent / "keil/dz_nvm.sct").read_text(encoding="utf-8"), f"{name}.sct 向量表放 Flash 起点")
        else:
            t = (by.parent / "ccs/dz_nvm_linker.cmd").read_text(encoding="utf-8")
            fl = re.search(r"FLASH\s+\(RX\)\s*: origin = (0x\w+), length = (0x\w+)", t)
            nv = re.search(r"DZ_NVM\s+\(R\)\s*: origin = (0x\w+), length = (0x\w+)", t)
            check(int(fl[1], 16) + int(fl[2], 16) == base and (int(nv[1], 16), int(nv[2], 16)) == (base, size)
                  and base + size == fend, f"{name}.cmd FLASH 截到 0x{base:05X}，DZ_NVM 到 Flash 末尾")
            check(f"__dz_nvm_base = 0x{base:08X};" in t and "Copyright (C) 2023 Texas Instruments" in t, f"{name}.cmd 有 __dz_nvm_base、保留 TI 版权")
            ps = next((by.parent / "ccs").glob("*.projectspec")).read_text(encoding="utf-8")
            check(f"-DDZ_NVM_KB={mcu['nvm_kb']}u" in ps and 'path="dz_nvm_linker.cmd"' in ps, f"{name} projectspec 带宏与 .cmd")
            sc = next((by.parent / "ccs").glob("*.syscfg")).read_text(encoding="utf-8")
            check(re.search(r"^ProjectConfig\.genLinker\s*=\s*false;", sc, re.M) is not None, f"{name}.syscfg 关掉 SysConfig 链接文件生成")
    check(n >= 5, f"{n} 块板开了 nvm_kb")
    # keil_inject --board 端到端（会先 make gen）
    with tempfile.TemporaryDirectory() as td:
        uv = pathlib.Path(td) / "MDK-ARM" / "car.uvprojx"
        uv.parent.mkdir()
        uv.write_text("""<?xml version="1.0"?><Project><Targets><Target><TargetName>T</TargetName><TargetOption><TargetArmAds>
<Cads><VariousControls><Define>USE_HAL_DRIVER</Define><IncludePath></IncludePath></VariousControls></Cads>
<Aads><VariousControls><Define></Define><IncludePath></IncludePath></VariousControls></Aads>
<LDads><umfTarg>1</umfTarg><ScatterFile></ScatterFile></LDads></TargetArmAds></TargetOption>
    <Groups>
      <Group>
        <GroupName>App</GroupName>
      </Group>
    </Groups></Target></Targets></Project>
""", encoding="utf-8")
        r = subprocess.run([sys.executable, "tools/keil_inject.py", str(uv), "--board", "stm32f103c8t6-car-cubemx", "--app", "car_2wd"],
                           cwd=ROOT, capture_output=True, text=True)
        t = uv.read_text(encoding="utf-8")
        sct = re.search(r"<ScatterFile>(.*?)</ScatterFile>", t)
        ok = r.returncode == 0 and "<umfTarg>0</umfTarg>" in t and "DZ_NVM_KB=4u" in t and "DZ_FLASH_KB=64u" in t and sct \
            and (uv.parent / sct[1].replace("\\", "/")).resolve() == (ROOT / "boards/stm32f103c8t6-car-cubemx/keil/dz_nvm.sct").resolve()
        check(bool(ok), f"keil_inject --board：Scatter File={sct[1] if sct else None}、关 Target 布局、加 DZ_NVM_KB/DZ_FLASH_KB {r.stderr[-300:]}")
    print(f"test_ide_nvm：{'全部通过' if not fails else f'{fails} 项失败'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
