#!/usr/bin/env python3
"""把 ADS1256 / ST7735 / ILI9488 三个原样拷来的驱动里直接调用的 STM32 HAL 换成 pal_* 调用——这是唯一的改动。
规则（逐条正则，见 RULES）：HAL_GPIO_WritePin(port, pin, v) → pal_gpio_write(port, v)；HAL_GPIO_ReadPin(port, pin) → pal_gpio_level(port)；
HAL_SPI_Transmit*(h, buf, n, ...) → pal_spi_tx(h, buf, n)；HAL_SPI_Receive(h, buf, n, t) → pal_spi_rx(h, buf, n)；HAL_Delay → pal_delay_ms；
GPIO_PIN_SET/RESET → true/false；SPI_HandleTypeDef* / GPIO_TypeDef* → pal_id_t；stm32*_hal.h → pal_hal_compat.h。
与上游的差异写到 <驱动>/PAL-CHANGES.patch。用法：python3 tools/pal_patch_hal.py（在 tools/vendor_drivers.py 之后跑）"""
import difflib, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
O = ROOT / "firmware/drivers/other"
A = r"((?:[^,()]|\([^()]*\))+)"   # 一个实参（允许一层括号）
RULES = [
    (re.compile(r"#include\s+\"stm32\w+_hal(_spi)?\.h\"(?:\n#include\s+\"stm32\w+_hal_spi\.h\")?"), '#include "pal_hal_compat.h"'),
    (re.compile(r"HAL_GPIO_WritePin\(\s*" + A + r",\s*" + A + r",\s*" + A + r"\)"), r"pal_gpio_write(\1, \3)"),
    (re.compile(r"HAL_GPIO_ReadPin\(\s*" + A + r",\s*" + A + r"\)"), r"pal_gpio_level(\1)"),
    (re.compile(r"HAL_SPI_Transmit(?:_IT|_DMA)?\(\s*&?" + A + r",\s*" + A + r",\s*" + A + r"(?:,\s*" + A + r")?\)"), r"pal_spi_tx(\1, \2, \3)"),
    (re.compile(r"HAL_SPI_Receive\(\s*&?" + A + r",\s*" + A + r",\s*" + A + r",\s*" + A + r"\)"), r"pal_spi_rx(\1, \2, \3)"),
    (re.compile(r"HAL_Delay\("), "pal_delay_ms("),
    (re.compile(r"\bGPIO_PIN_SET\b"), "true"),
    (re.compile(r"\bGPIO_PIN_RESET\b"), "false"),
    (re.compile(r"\bSPI_HandleTypeDef\s*\*\s*"), "pal_id_t "),
    (re.compile(r"\bGPIO_TypeDef\s*\*\s*"), "pal_id_t "),
    (re.compile(r"\bextern\s+SPI_HandleTypeDef\b"), "extern pal_id_t"),
]
# 头文件里的引脚宏：原值是 CubeMX 的 GPIOx / GPIO_PIN_n，换成用户提供的 pal id 变量
PINMAC = re.compile(r"^(#define\s+(\w+?)_GPIO_Port\s+)GPIO[A-K]\b", re.M)
FILES = ["ads1256/inc/ads1255.h", "ads1256/src/ads1255.c", "st7735/st7735/st7735.h", "st7735/st7735/st7735.c",
         "ili9488/1-HOWTO/z_displ_ILI9XXX.h", "ili9488/1-HOWTO/z_displ_ILI9XXX.c"]


def upstream(rel: str) -> str:
    d = rel.split("/")[0]
    src = {"ads1256": "/workspace/refs/drivers/ads1256", "st7735": "/workspace/refs/drivers/st7735", "ili9488": "/workspace/refs/drivers/ili9xxx"}[d]
    sub = rel.split("/", 1)[1].replace("1-HOWTO/", "1-HOWTO/") if d != "st7735" else rel.split("/", 1)[1]
    return pathlib.Path(src, sub).read_text(encoding="utf-8", errors="surrogateescape")


def patch(t: str) -> str:
    for rx, rep in RULES:
        t = rx.sub(rep, t)
    t = PINMAC.sub(lambda m: f"{m.group(1)}{m.group(2).lower()}_pal", t)
    for name in sorted(set(re.findall(r"#define\s+(\w+_pal)\b", "")), key=str):
        pass
    return t


def main() -> int:
    diffs: dict[str, list[str]] = {}
    for rel in FILES:
        f = O / rel
        orig = upstream(rel)
        new = patch(orig)
        # 引脚宏指向的变量要声明（只在头文件里加 extern）
        if rel.endswith(".h"):
            vs = sorted(set(re.findall(r"_GPIO_Port\s+(\w+_pal)\b", new)))
            if vs:
                new = re.sub(r"(#include \"pal_hal_compat.h\"|#include <stdbool.h>)", lambda m: m.group(1) + "\n" + "".join(f"extern pal_id_t {v};\n" for v in vs), new, count=1)
                if "pal_hal_compat.h" not in new:
                    new = new.replace("#include <stdbool.h>", '#include <stdbool.h>\n#include "pal_hal_compat.h"', 1)
        if rel.endswith(".c") and "pal_hal_compat.h" not in new and "pal_" in new:
            new = new.replace('#include "', '#include "pal_hal_compat.h"\n#include "', 1)
        f.write_text(new, encoding="utf-8", errors="surrogateescape")
        diffs.setdefault(rel.split("/")[0], []).extend(difflib.unified_diff(orig.splitlines(True), new.splitlines(True), "a/" + rel, "b/" + rel))
    for d, lines in diffs.items():
        (O / d / "PAL-CHANGES.patch").write_text("".join(lines), encoding="utf-8", errors="surrogateescape")
        print(d, sum(1 for l in lines if l.startswith("+") and not l.startswith("+++")), "lines changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
