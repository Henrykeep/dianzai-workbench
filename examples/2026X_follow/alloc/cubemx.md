# CubeMX 配置清单（STM32F103C8T6）

> tools/alloc.py 生成。按顺序做完再 GENERATE；User Label 必须和逻辑名一致（docs/05 标签约定），之后 `tools/ioc_import.py` 导出 board.yaml、`make ioc-check` 核对。

## 1. System Core

- RCC：HSE = Crystal/Ceramic Resonator；Clock Configuration 里 HCLK = 72 MHz（APB1 36 MHz、定时器 ×2 = 72 MHz；APB2 72 MHz）
- SYS：Debug = Serial Wire（PA13/PA14 保留给 ST-Link / DAPLink；F1 这样还会释放 PA15/PB3/PB4 的 JTAG 功能）
- NVIC：Priority Group = 4 bits pre-emption（docs/11）

## 2. 引脚与外设

| 引脚 | 功能 | User Label |
|---|---|---|
| PA12 | GPIO_Input（上拉） | LINE0 |
| PB12 | GPIO_Input（上拉） | LINE1 |
| PB13 | GPIO_Input（上拉） | LINE2 |
| PB14 | GPIO_Input（上拉） | LINE3 |
| PB15 | GPIO_Input（上拉） | LINE4 |
| PA0 | GPIO_Input（上拉） | LINE5 |
| PA1 | GPIO_Input（上拉） | LINE6 |
| PA4 | GPIO_Input（上拉） | LINE7 |
| PA5 | GPIO_Output | MOTOR_A_IN1 |
| PA10 | GPIO_Output | MOTOR_A_IN2 |
| PA11 | GPIO_Output | MOTOR_B_IN1 |
| PB0 | GPIO_Output | MOTOR_B_IN2 |
| PB1 | GPIO_Input（上拉） | KEY1 |
| PA8 | TIM1_CH1 | MOTOR_A |
| PA9 | TIM1_CH2 | MOTOR_B |
| PA6 | TIM3_CH1 | MOTOR_A_A |
| PA7 | TIM3_CH2 | MOTOR_A_B |
| PB6 | TIM4_CH1 | MOTOR_B_A |
| PB7 | TIM4_CH2 | MOTOR_B_B |
| PA2 | USART2_TX | PEER_TX |
| PA3 | USART2_RX | PEER_RX |
| PB10 | USART3_TX | LINK_TX |
| PB11 | USART3_RX | LINK_RX |
| PB8 | I2C1_SCL | OLED_SCL |
| PB9 | I2C1_SDA | OLED_SDA |

## 3. 定时器

| 定时器 | 模式 | 参数 |
|---|---|---|
| TIM1 | PWM Generation CH1, CH2 | 时钟 72 MHz → Prescaler=0，Counter Period=3599（20000 Hz，占空分辨率 3600 级）；auto-reload preload Enable |
| TIM3 | Combined Channels = Encoder Mode TI1 and TI2 | Counter Period=65535；Input Filter 6–10（抗电机干扰）；MOTOR_A |
| TIM4 | Combined Channels = Encoder Mode TI1 and TI2 | Counter Period=65535；Input Filter 6–10（抗电机干扰）；MOTOR_B |
| TIM2 | Clock Source = Internal Clock（不出引脚） | 控制节拍 CTRL：PSC/ARR 不用在 CubeMX 填（pal_timer_start 运行时按周期设）；开 TIM2 global interrupt，抢占优先级比所有串口高一级 |

## 4. 串口、DMA 与中断优先级

| 串口 | 逻辑名 | 波特率 | RX DMA（Circular） | NVIC 抢占优先级 |
|---|---|---|---|---|
| USART2 | PEER | 115200 | DMA1 Stream6 Channel0；同时开 USART2 global interrupt（IDLE 断帧） | 4 |
| USART3 | LINK | 115200 | DMA1 Stream3 Channel0；同时开 USART3 global interrupt（IDLE 断帧） | 5 |

优先级规则（数字小 = 先响应）：执行器链路（如 QD4310）> 视觉 > 姿态 > 调试链路 > 其他；控制节拍定时器比所有串口高一级。

## 5. Project Manager

- Toolchain/IDE：MDK-ARM（Keil）或 STM32CubeIDE / Makefile（EIDE）；Code Generator 勾选 “Generate peripheral initialization as a pair of .c/.h”

