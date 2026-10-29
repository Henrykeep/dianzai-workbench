#!/usr/bin/env python3
"""生成物一致性检查（G1，docs/27）：CubeMX 生成的代码是否还和 .ioc / board.yaml 对得上。

为什么要有：换引脚时只改了 .ioc 却没在 CubeMX 里重新 GENERATE（或手改了 Core/），
MX_GPIO_Init 会继续初始化旧引脚——旧引脚现在可能接着别的器件，上电就打架；
链接脚本比芯片 flash 大时，程序超出后不会报错，烧进去才跑飞。两者编译都能过，只有上板才暴露。

检查（每块 port: stm32-cubemx 的板）：
  C1 .ioc 里 Signal=GPIO_Input/GPIO_Output/GPXTI 的引脚，MX_GPIO_Init 必须初始化；
  C2 MX_GPIO_Init 初始化的引脚，.ioc 里必须仍是 GPIO（否则 = 残留的旧引脚）；
  C3 链接脚本必须带"程序 ≤ __flash_kb*1024"的 ASSERT（Makefile 用 --defsym 传 board.yaml 的 mcu.flash_kb），
     且 MEMORY 的 FLASH LENGTH ≥ flash_kb（否则同系列大容量型号如 VGT6 用不满）。
     注：MEMORY 写芯片系列最大值是有意的（docs/notes/implemented/2026-10-29-flash-assert.md），审计初稿把它误判为缺口。
用法：check_gen_consistency.py [--selftest]
"""
from __future__ import annotations

import pathlib
import re
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def ioc_gpio(text: str) -> set[tuple[str, int]]:
    pins = set()
    for m in re.finditer(r"^P([A-K])(\d+)(?:-[\w-]+)?\.Signal=(GPIO_Input|GPIO_Output|GPXTI\d*)\s*$", text, re.M):
        pins.add((m.group(1), int(m.group(2))))
    return pins


def init_gpio(core: pathlib.Path) -> set[tuple[str, int]]:
    macros: dict[str, str] = {}
    for h in core.glob("Inc/*.h"):
        for m in re.finditer(r"#define\s+(\w+)\s+(GPIO_PIN_\d+|GPIO[A-K])\b", h.read_text(encoding="utf-8", errors="replace")):
            macros[m.group(1)] = m.group(2)
    body = ""
    for c in list(core.glob("Src/gpio.c")) + list(core.glob("Src/main.c")):
        m = re.search(r"void\s+MX_GPIO_Init\s*\(\s*void\s*\)\s*\{(.*?)\n\}", c.read_text(encoding="utf-8", errors="replace"), re.S)
        if m:
            body = m.group(1)
            break
    pins = set()
    cur: list[str] = []
    for m in re.finditer(r"GPIO_InitStruct\.Pin\s*=\s*([^;]+);|HAL_GPIO_Init\(\s*(\w+)\s*,", body):
        if m.group(1):
            cur = [t.strip() for t in m.group(1).split("|")]
        else:
            port = macros.get(m.group(2), m.group(2))
            for t in cur:
                pin = macros.get(t, t)
                pm = re.fullmatch(r"GPIO_PIN_(\d+)", pin)
                if not pm:
                    continue
                if t.endswith("_Pin"):  # 标签宏：端口以 <标签>_GPIO_Port 为准
                    port = macros.get(t[:-4] + "_GPIO_Port", port)
                pins.add((port.replace("GPIO", ""), int(pm.group(1))))
    return pins


def ld_flash_kb(ld: pathlib.Path) -> int | None:
    m = re.search(r"FLASH\s*\(rx\)\s*:\s*ORIGIN\s*=\s*\w+\s*,\s*LENGTH\s*=\s*(\d+)\s*([KM])", ld.read_text())
    if not m:
        return None
    return int(m.group(1)) * (1024 if m.group(2) == "M" else 1)


def check_board(by: pathlib.Path) -> list[str]:
    b = yaml.safe_load(by.read_text(encoding="utf-8"))
    if b.get("port") != "stm32-cubemx":
        return []
    d = by.parent
    errs = []
    iocs = list(d.glob("cubemx/*.ioc"))
    core = d / "cubemx" / "Core"
    name = d.name
    if iocs and core.is_dir():
        want, have = ioc_gpio(iocs[0].read_text(encoding="utf-8")), init_gpio(core)
        for p in sorted(want - have):
            errs.append(f"{name}: .ioc 里 P{p[0]}{p[1]} 是 GPIO，但 MX_GPIO_Init 没初始化它——改完 .ioc 后在 CubeMX 里点 GENERATE CODE")
        for p in sorted(have - want):
            errs.append(f"{name}: MX_GPIO_Init 还在初始化 P{p[0]}{p[1]}，.ioc 里它已不是 GPIO（残留旧引脚）——在 CubeMX 里重新 GENERATE CODE，不要手改 Core/")
    fk = (b.get("mcu") or {}).get("flash_kb")
    for ld in d.glob("cubemx/*.ld"):
        lk = ld_flash_kb(ld)
        txt = ld.read_text(encoding="utf-8")
        if not re.search(r"ASSERT\([^;]*<=\s*__flash_kb\s*\*\s*1024", txt):
            errs.append(f"{name}: {ld.name} 缺少按 __flash_kb 检查程序大小的 ASSERT——程序超出芯片 flash 时链接不报错、烧录后跑飞")
        if fk and lk and lk < fk:
            errs.append(f"{name}: {ld.name} FLASH LENGTH={lk}K 小于 board.yaml flash_kb={fk}——核对芯片型号")
    return errs


def run(root: pathlib.Path) -> list[str]:
    errs = []
    for by in sorted(root.glob("boards/*/board.yaml")):
        errs += check_board(by)
    return errs


def selftest() -> int:
    ok = True
    with tempfile.TemporaryDirectory() as t:
        d = pathlib.Path(t) / "boards/x"
        (d / "cubemx/Core/Inc").mkdir(parents=True)
        (d / "cubemx/Core/Src").mkdir(parents=True)
        (d / "board.yaml").write_text("port: stm32-cubemx\nmcu: {flash_kb: 64}\n")
        (d / "cubemx/x.ioc").write_text("PC13.Signal=GPIO_Output\nPA9.Signal=USART1_TX\n")
        (d / "cubemx/Core/Inc/main.h").write_text("#define LED_Pin GPIO_PIN_8\n#define LED_GPIO_Port GPIOA\n")
        (d / "cubemx/Core/Src/main.c").write_text("void MX_GPIO_Init(void)\n{\n  GPIO_InitStruct.Pin = LED_Pin;\n  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);\n}\n")
        (d / "cubemx/x.ld").write_text("  FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 32K\n")
        e = run(pathlib.Path(t))
        for key in ("PC13", "PA8", "ASSERT", "32K"):
            hit = any(key in x for x in e)
            ok &= hit
            print(f"{'✓' if hit else '✗'} selftest 能报出 {key}")
        (d / "cubemx/x.ioc").write_text("PA8.Signal=GPIO_Output\n")
        (d / "cubemx/x.ld").write_text("  FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 128K\n  ASSERT(_etext - ORIGIN(FLASH) <= __flash_kb * 1024, \"x\")\n")
        e = run(pathlib.Path(t))
        ok &= not e
        print(f"{'✓' if not e else '✗'} selftest 一致时不报 {e}")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    errs = run(ROOT)
    for e in errs:
        print("✗", e)
    if not errs:
        print("✓ CubeMX 生成物与 .ioc / board.yaml 一致（GPIO 初始化、flash 大小）")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
