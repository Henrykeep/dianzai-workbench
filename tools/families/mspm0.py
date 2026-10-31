"""MSPM0G350x 资源知识：从 SDK 头文件 mspm0g350x.h 的 IOMUX 宏**自动生成**（不手抄），供 validate_board.py 用。

事实来源：TI mspm0-sdk（third_party/mspm0-sdk，版本见 tools/fetch_third_party.sh）；
"QEI 只有 TIMG8""PA0/PA1 开漏""PA19/20 SWD""PA21/23 VREF"等坑参考 mspm0g-contest-skill 调研（docs/参考来源.md），
并以 TI 数据手册为准。未上板验证。
"""
from __future__ import annotations
import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[2]
HDR = ROOT / "third_party/mspm0-sdk/source/ti/devices/msp/m0p/mspm0g350x.h"

QEI_TIMERS = {"TIMG8"}                       # G350x 上唯一带 QEI 的定时器
TIMER_BITS = {"TIMA0": 16, "TIMA1": 16, "TIMG0": 16, "TIMG6": 16, "TIMG7": 16, "TIMG8": 16, "TIMG12": 32}
# SWD 调试口：占用即报错（#56），见 boardlib.swd_msg
SWD_PINS = {"PA19": "SWDIO", "PA20": "SWCLK"}
TRAP_PINS = {
    "PA0": "开漏输出（作 UART/输出需外部上拉；与 BSL 有关）",
    "PA1": "开漏输出（作 UART/输出需外部上拉；与 BSL 有关）",
    "PA19": "SWDIO，占用后无法调试/烧录",
    "PA20": "SWCLK，占用后无法调试/烧录",
    "PA21": "VREF-，作 IO 会影响 ADC 基准",
    "PA23": "VREF+，作 IO 会影响 ADC 基准",
    **{f"PA{i}": "时钟脚（HFXT/LFXT/CLK_OUT 相关），未确认原理图前别占" for i in (2, 3, 4, 5, 6)},
}


def load_iomux(path: pathlib.Path = HDR) -> dict[str, set[str]]:
    """{'PA0': {'GPIOA_DIO00','UART0_TX','TIMA0_CCP0',...}}；SDK 未下载时返回 {}。"""
    if not path.exists():
        return {}
    by_cm: dict[int, set[str]] = {}
    for cm, fn in re.findall(r"#define IOMUX_PINCM(\d+)_PF_(\w+?)\s+\(\(uint32_t\)", path.read_text(encoding="utf-8", errors="replace")):
        by_cm.setdefault(int(cm), set()).add(fn)
    out = {}
    for fns in by_cm.values():
        g = next((f for f in fns if re.fullmatch(r"GPIO[AB]_DIO\d\d", f)), None)
        if g:
            out[f"P{g[4]}{int(g[-2:])}"] = fns
    return out


def timers(iomux: dict[str, set[str]]) -> set[str]:
    return {m[1] for fns in iomux.values() for f in fns for m in [re.match(r"(TIM[AG]\d+)_", f)] if m}
