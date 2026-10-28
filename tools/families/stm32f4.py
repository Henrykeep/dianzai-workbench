"""STM32F405/407 系列的资源知识表，供 validate_board.py 做冲突检查、gen_board.py 生成代码。

来源与可信度（请如实对待）：
  - 引脚复用表：依据 ST 数据手册 DS8626《STM32F405xx/STM32F407xx》Table 9
    "Alternate function mapping" 人工整理，只收录常用的 TIM/USART/ADC 功能。
  - DMA 请求映射：依据参考手册 RM0090 Table 42/43（DMA1/DMA2 request mapping）。
  - 定时器总线与位宽：依据 RM0090 / DS8626。
  这些表未经工具逐项与 PDF 自动比对。新增或修改条目时请对照手册，或在 STM32CubeMX
  里把同样的引脚配置一遍确认；validate_board.py 对不在表中的组合只给"未核实"警告，不放行为错误。
"""

# 定时器：(所在总线 APB1/APB2, 计数位宽, 能否做正交编码, 能否 PWM, 中断向量名)
TIMERS = {
    "TIM1":  ("APB2", 16, True,  True,  "TIM1_UP_TIM10_IRQ"),
    "TIM2":  ("APB1", 32, True,  True,  "TIM2_IRQ"),
    "TIM3":  ("APB1", 16, True,  True,  "TIM3_IRQ"),
    "TIM4":  ("APB1", 16, True,  True,  "TIM4_IRQ"),
    "TIM5":  ("APB1", 32, True,  True,  "TIM5_IRQ"),
    "TIM6":  ("APB1", 16, False, False, "TIM6_DAC_IRQ"),
    "TIM7":  ("APB1", 16, False, False, "TIM7_IRQ"),
    "TIM8":  ("APB2", 16, True,  True,  "TIM8_UP_TIM13_IRQ"),
    "TIM9":  ("APB2", 16, False, True,  "TIM1_BRK_TIM9_IRQ"),
    "TIM10": ("APB2", 16, False, True,  "TIM1_UP_TIM10_IRQ"),
    "TIM11": ("APB2", 16, False, True,  "TIM1_TRG_COM_TIM11_IRQ"),
    "TIM12": ("APB1", 16, False, True,  "TIM8_BRK_TIM12_IRQ"),
    "TIM13": ("APB1", 16, False, True,  "TIM8_UP_TIM13_IRQ"),
    "TIM14": ("APB1", 16, False, True,  "TIM8_TRG_COM_TIM14_IRQ"),
}

# 定时器 -> GPIO 复用号（AF1: TIM1/2，AF2: TIM3/4/5，AF3: TIM8/9/10/11，AF9: TIM12/13/14）
TIMER_AF = {"TIM1": 1, "TIM2": 1, "TIM3": 2, "TIM4": 2, "TIM5": 2,
            "TIM8": 3, "TIM9": 3, "TIM10": 3, "TIM11": 3,
            "TIM12": 9, "TIM13": 9, "TIM14": 9}

# (定时器, 通道) -> 可用引脚（仅收录 LQFP100 封装存在的常用引脚）
TIMER_CH_PINS = {
    ("TIM1", 1): ["PA8", "PE9"],   ("TIM1", 2): ["PA9", "PE11"],
    ("TIM1", 3): ["PA10", "PE13"], ("TIM1", 4): ["PA11", "PE14"],
    ("TIM2", 1): ["PA0", "PA5", "PA15"], ("TIM2", 2): ["PA1", "PB3"],
    ("TIM2", 3): ["PA2", "PB10"],  ("TIM2", 4): ["PA3", "PB11"],
    ("TIM3", 1): ["PA6", "PB4", "PC6"], ("TIM3", 2): ["PA7", "PB5", "PC7"],
    ("TIM3", 3): ["PB0", "PC8"],   ("TIM3", 4): ["PB1", "PC9"],
    ("TIM4", 1): ["PB6", "PD12"],  ("TIM4", 2): ["PB7", "PD13"],
    ("TIM4", 3): ["PB8", "PD14"],  ("TIM4", 4): ["PB9", "PD15"],
    ("TIM5", 1): ["PA0"], ("TIM5", 2): ["PA1"], ("TIM5", 3): ["PA2"], ("TIM5", 4): ["PA3"],
    ("TIM8", 1): ["PC6"], ("TIM8", 2): ["PC7"], ("TIM8", 3): ["PC8"], ("TIM8", 4): ["PC9"],
    ("TIM9", 1): ["PA2", "PE5"], ("TIM9", 2): ["PA3", "PE6"],
    ("TIM10", 1): ["PB8"], ("TIM11", 1): ["PB9"],
    ("TIM12", 1): ["PB14"], ("TIM12", 2): ["PB15"],
    ("TIM13", 1): ["PA6"], ("TIM14", 1): ["PA7"],
}

# 串口：AF 号、总线、TX/RX 可用引脚、中断名
UARTS = {
    "USART1": (7, "APB2", ["PA9", "PB6"],  ["PA10", "PB7"], "USART1_IRQ"),
    "USART2": (7, "APB1", ["PA2", "PD5"],  ["PA3", "PD6"],  "USART2_IRQ"),
    "USART3": (7, "APB1", ["PB10", "PC10", "PD8"], ["PB11", "PC11", "PD9"], "USART3_IRQ"),
    "UART4":  (8, "APB1", ["PA0", "PC10"], ["PA1", "PC11"], "UART4_IRQ"),
    "UART5":  (8, "APB1", ["PC12"],        ["PD2"],         "UART5_IRQ"),
    "USART6": (8, "APB2", ["PC6", "PG14"], ["PC7", "PG9"],         "USART6_IRQ"),
}

# 串口 DMA：(DMA 控制器, 数据流, 通道)；每项第一个为默认选择，后面是备选
UART_DMA_RX = {
    "USART1": [(2, 2, 4), (2, 5, 4)], "USART2": [(1, 5, 4)], "USART3": [(1, 1, 4)],
    "UART4":  [(1, 2, 4)],            "UART5":  [(1, 0, 4)], "USART6": [(2, 1, 5), (2, 2, 5)],
}
UART_DMA_TX = {
    "USART1": [(2, 7, 4)], "USART2": [(1, 6, 4)], "USART3": [(1, 3, 4), (1, 4, 7)],
    "UART4":  [(1, 4, 4)], "UART5":  [(1, 7, 4)], "USART6": [(2, 6, 5), (2, 7, 5)],
}

# ADC 通道 -> 引脚（ADC1/2/3 的 IN0..IN15，ADC3 部分通道在 PF 口，LQFP100 不全，这里只收 ADC1/ADC2）
ADC_CH_PINS = {0: "PA0", 1: "PA1", 2: "PA2", 3: "PA3", 4: "PA4", 5: "PA5", 6: "PA6", 7: "PA7",
               8: "PB0", 9: "PB1", 10: "PC0", 11: "PC1", 12: "PC2", 13: "PC3", 14: "PC4", 15: "PC5"}
ADCS = ["ADC1", "ADC2"]

# 调试/启动相关、复用前要三思的引脚
RESERVED_PINS = {
    "PA13": "SWDIO（占用后无法用 SWD 下载/调试）",
    "PA14": "SWCLK（占用后无法用 SWD 下载/调试）",
    "PH0": "OSC_IN（HSE 晶振）", "PH1": "OSC_OUT（HSE 晶振）",
    "PC14": "OSC32_IN（LSE 晶振）", "PC15": "OSC32_OUT（LSE 晶振）",
}

import re
PIN_RE = re.compile(r"^P([A-I])(1[0-5]|[0-9])$")

# I2C（AF4）：总线、SCL 可选、SDA 可选（STM32F407 数据手册 DS8626 表 9 复用功能映射）
I2CS = {
    "I2C1": ("APB1", ["PB6", "PB8"], ["PB7", "PB9"]),
    "I2C2": ("APB1", ["PB10", "PF1", "PH4"], ["PB11", "PF0", "PH5"]),
    "I2C3": ("APB1", ["PA8", "PH7"], ["PC9", "PH8"]),
}
# SPI：AF 号、总线、SCK / MISO / MOSI 可选（同上表；SPI1/2 为 AF5，SPI3 为 AF6）
SPIS = {
    "SPI1": (5, "APB2", ["PA5", "PB3"], ["PA6", "PB4"], ["PA7", "PB5"]),
    "SPI2": (5, "APB1", ["PB10", "PB13", "PI1"], ["PB14", "PC2", "PI2"], ["PB15", "PC3", "PI3"]),
    "SPI3": (6, "APB1", ["PB3", "PC10"], ["PB4", "PC11"], ["PB5", "PC12"]),
}
