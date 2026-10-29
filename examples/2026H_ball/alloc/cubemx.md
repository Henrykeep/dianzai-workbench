# CubeMX 配置清单（STM32F407VETx）

> tools/alloc.py 生成。按顺序做完再 GENERATE；User Label 必须和逻辑名一致（docs/05 标签约定），之后 `tools/ioc_import.py` 导出 board.yaml、`make ioc-check` 核对。

## 1. System Core

- RCC：HSE = Crystal/Ceramic Resonator；Clock Configuration 里 HCLK = 168 MHz（APB1 42 MHz / APB2 84 MHz，定时器时钟各 ×2）
- SYS：Debug = Serial Wire（PA13/PA14 保留给 ST-Link / DAPLink）
- NVIC：Priority Group = 4 bits pre-emption（docs/11）

## 2. 引脚与外设

| 引脚 | 功能 | User Label |
|---|---|---|
| PE0 | GPIO_Input（上拉） | SENSOR1 |
| PE1 | GPIO_Input（上拉） | SENSOR2 |
| PE2 | GPIO_Input（上拉） | SENSOR3 |
| PE3 | GPIO_Input（上拉） | SENSOR4 |
| PE4 | GPIO_Input（上拉） | SENSOR5 |
| PE5 | GPIO_Input（上拉） | SENSOR6 |
| PE6 | GPIO_Input（上拉） | SENSOR7 |
| PE7 | GPIO_Input（上拉） | SENSOR8 |
| PE8 | GPIO_Output | MOTOR_A_IN1 |
| PE9 | GPIO_Output | MOTOR_A_IN2 |
| PE10 | GPIO_Output | MOTOR_B_IN1 |
| PE11 | GPIO_Output | MOTOR_B_IN2 |
| PE12 | GPIO_Input（上拉） | KEY1 |
| PA8 | TIM1_CH1 | MOTOR_A |
| PA9 | TIM1_CH2 | MOTOR_B |
| PA6 | TIM3_CH1 | MOTOR_A_A |
| PA7 | TIM3_CH2 | MOTOR_A_B |
| PB6 | TIM4_CH1 | MOTOR_B_A |
| PB7 | TIM4_CH2 | MOTOR_B_B |
| PA2 | USART2_TX | VISION_TX |
| PA3 | USART2_RX | VISION_RX |
| PB10 | USART3_TX | BEAM_TX |
| PB11 | USART3_RX | BEAM_RX |
| PA0 | UART4_TX | LINK_TX |
| PA1 | UART4_RX | LINK_RX |
| PB8 | I2C1_SCL | OLED_SCL |
| PB9 | I2C1_SDA | OLED_SDA |

## 3. 定时器

| 定时器 | 模式 | 参数 |
|---|---|---|
| TIM1 | PWM Generation CH1, CH2 | 时钟 168 MHz → Prescaler=0，Counter Period=8399（20000 Hz，占空分辨率 8400 级）；auto-reload preload Enable |
| TIM3 | Combined Channels = Encoder Mode TI1 and TI2 | Counter Period=65535；Input Filter 6–10（抗电机干扰）；MOTOR_A |
| TIM4 | Combined Channels = Encoder Mode TI1 and TI2 | Counter Period=65535；Input Filter 6–10（抗电机干扰）；MOTOR_B |

## 4. 串口、DMA 与中断优先级

| 串口 | 逻辑名 | 波特率 | RX DMA（Circular） | NVIC 抢占优先级 |
|---|---|---|---|---|
| USART3 | BEAM | 921600 | DMA1 Stream1 Channel4；同时开 USART3 global interrupt（IDLE 断帧） | 2 |
| USART2 | VISION | 115200 | DMA1 Stream5 Channel4；同时开 USART2 global interrupt（IDLE 断帧） | 3 |
| UART4 | LINK | 115200 | DMA1 Stream2 Channel4；同时开 UART4 global interrupt（IDLE 断帧） | 5 |

优先级规则（数字小 = 先响应）：执行器链路（如 QD4310）> 视觉 > 姿态 > 调试链路 > 其他；控制节拍定时器比所有串口高一级。

## 5. Project Manager

- Toolchain/IDE：MDK-ARM（Keil）或 STM32CubeIDE / Makefile（EIDE）；Code Generator 勾选 “Generate peripheral initialization as a pair of .c/.h”

