"""STM32F103x8/xB（中容量，重点 C8T6 / CBT6 的 LQFP48）资源知识表，供 validate_board / alloc 使用。

来源与可信度（请如实对待）：
  - 引脚与重映射：ST 数据手册 DS5319《STM32F103x8/xB》Table 5 “Pin definitions”（LQFP48 列）
    与参考手册 RM0008 §9.3 “Alternate function I/O and debug configuration (AFIO)”（Table 41–55 重映射）。
  - DMA：RM0008 Table 78 “Summary of DMA1 requests for each channel”（F1 的外设→通道是固定的，没有备选）。
  - 只收录 LQFP48 存在的引脚：PA0–15、PB0–15、PC13–15、PD0–1（OSC）。PC6–9、PD12–15 等重映射目标在 48 脚上不存在，不收。
  人工整理，未与 PDF 自动逐项比对；改表请对照手册或在 CubeMX 选 STM32F103C8Tx 配一遍。

与 F4 的关键区别：F1 没有“每个引脚任选 AF”，而是**整组重映射**（AFIO_MAPR）——同一定时器/串口的所有通道
必须来自同一组。所以这里另有 TIMER_REMAP / UART_REMAP / I2C_REMAP / SPI_REMAP，boardlib 和 alloc.py 按组检查和分配。
"""
import re

PACKAGE = "LQFP48"

# 定时器：(总线, 位宽, 能否编码器, 能否 PWM, 中断名)。中容量只有 TIM1–4
TIMERS = {
    "TIM1": ("APB2", 16, True, True, "TIM1_UP_IRQ"),
    "TIM2": ("APB1", 16, True, True, "TIM2_IRQ"),
    "TIM3": ("APB1", 16, True, True, "TIM3_IRQ"),
    "TIM4": ("APB1", 16, True, True, "TIM4_IRQ"),
}
# 72 MHz：APB2 = 72 MHz；APB1 = 36 MHz，定时器时钟 ×2 = 72 MHz（RM0008 §7.2 时钟树）
TIM_CLK = {"APB1": 72_000_000, "APB2": 72_000_000}
SYSCLK = 72_000_000

# 重映射组：每组 {通道: 引脚}；第一组是默认（无重映射）
TIMER_REMAP = {
    "TIM1": [{1: "PA8", 2: "PA9", 3: "PA10", 4: "PA11"}],                     # 全重映射到 PE 口，48 脚没有
    "TIM2": [{1: "PA0", 2: "PA1", 3: "PA2", 4: "PA3"},                         # 默认
             {1: "PA15", 2: "PB3", 3: "PA2", 4: "PA3"},                        # 部分重映射 1
             {1: "PA0", 2: "PA1", 3: "PB10", 4: "PB11"},                       # 部分重映射 2
             {1: "PA15", 2: "PB3", 3: "PB10", 4: "PB11"}],                     # 完全重映射
    "TIM3": [{1: "PA6", 2: "PA7", 3: "PB0", 4: "PB1"},
             {1: "PB4", 2: "PB5", 3: "PB0", 4: "PB1"}],                        # 部分重映射；完全重映射在 PC6–9，48 脚没有
    "TIM4": [{1: "PB6", 2: "PB7", 3: "PB8", 4: "PB9"}],                        # 重映射到 PD12–15，48 脚没有
}
TIMER_CH_PINS = {}
for _t, _gs in TIMER_REMAP.items():
    for _g in _gs:
        for _c, _p in _g.items():
            TIMER_CH_PINS.setdefault((_t, _c), [])
            if _p not in TIMER_CH_PINS[(_t, _c)]:
                TIMER_CH_PINS[(_t, _c)].append(_p)

# 串口：(AF 占位 0, 总线, TX 可选, RX 可选, 中断名)；可选列表由重映射组展开
UART_REMAP = {
    "USART1": [("PA9", "PA10"), ("PB6", "PB7")],
    "USART2": [("PA2", "PA3")],                 # 重映射 PD5/PD6，48 脚没有
    "USART3": [("PB10", "PB11")],               # 重映射 PC10/11、PD8/9，48 脚没有
}
UARTS = {u: (0, "APB2" if u == "USART1" else "APB1", [g[0] for g in gs], [g[1] for g in gs], f"{u}_IRQ")
         for u, gs in UART_REMAP.items()}

# DMA1 固定通道：(控制器, 通道, 0)——与 F4 表同形状，boardlib/alloc 按 (控制器, 通道) 判冲突
UART_DMA_RX = {"USART1": [(1, 5, 0)], "USART2": [(1, 6, 0)], "USART3": [(1, 3, 0)]}
UART_DMA_TX = {"USART1": [(1, 4, 0)], "USART2": [(1, 7, 0)], "USART3": [(1, 2, 0)]}

# ADC1/ADC2：IN0–IN9（48 脚只有这 10 路外部通道）
ADC_CH_PINS = {0: "PA0", 1: "PA1", 2: "PA2", 3: "PA3", 4: "PA4", 5: "PA5", 6: "PA6", 7: "PA7", 8: "PB0", 9: "PB1"}
ADCS = ["ADC1", "ADC2"]

I2C_REMAP = {"I2C1": [("PB6", "PB7"), ("PB8", "PB9")], "I2C2": [("PB10", "PB11")]}
I2CS = {i: ("APB1", [g[0] for g in gs], [g[1] for g in gs]) for i, gs in I2C_REMAP.items()}
SPI_REMAP = {"SPI1": [("PA5", "PA6", "PA7"), ("PB3", "PB4", "PB5")], "SPI2": [("PB13", "PB14", "PB15")]}   # (SCK, MISO, MOSI)
SPIS = {s: (0, "APB2" if s == "SPI1" else "APB1", [g[0] for g in gs], [g[1] for g in gs], [g[2] for g in gs])
        for s, gs in SPI_REMAP.items()}

# SWD 调试口：占用即报错（#56），见 boardlib.swd_msg
SWD_PINS = {"PA13": "SWDIO", "PA14": "SWCLK"}
RESERVED_PINS = {
    "PA13": "SWDIO（占用后无法用 SWD 下载/调试）",
    "PA14": "SWCLK（占用后无法用 SWD 下载/调试）",
    "PD0": "OSC_IN（HSE 晶振）", "PD1": "OSC_OUT（HSE 晶振）",
    "PC14": "OSC32_IN（LSE 晶振；不接 LSE 时可作低速 GPIO，驱动能力 3 mA）",
    "PC15": "OSC32_OUT（同上）",
    "PB2": "BOOT1（多数板子接了下拉/跳帽）",
}
# 默认是 JTAG 功能：CubeMX 里 SYS → Debug = Serial Wire 才释放为 GPIO/重映射脚（RM0008 §9.3.5）
JTAG_PINS = {"PA15": "JTDI", "PB3": "JTDO", "PB4": "NJTRST"}
TRAP_PINS = {"PC13": "驱动能力弱（3 mA、最高 2 MHz），只适合 LED/慢信号；多数蓝丸板上接了板载 LED",
             **{p: f"上电默认是 {n}：CubeMX SYS 里 Debug 选 Serial Wire 才能当普通脚用" for p, n in JTAG_PINS.items()}}

GPIO_PINS = [f"PA{i}" for i in range(16)] + [f"PB{i}" for i in range(16)] + ["PC13", "PC14", "PC15"]
PIN_RE = re.compile(r"^P(?:[AB](?:1[0-5]|[0-9])|C1[3-5]|D[01])$")
