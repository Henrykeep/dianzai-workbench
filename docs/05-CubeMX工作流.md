# 05 STM32 CubeMX 工作流（推荐）

> 标注约定：**【已实测】** = 本仓库在 PC 上用测试/编译实际跑过（2026-10-28，Asia/Shanghai）；**【未验证】** = 设计意图或推断，尚未在真实硬件上做实验。实验是检验真理的唯一标准——【未验证】的内容上板前不要当结论。

**STM32 只用 CubeMX + HAL**：CubeMX 的 .ioc 是唯一配置源（时钟、引脚、DMA、中断），框架只包装它生成的句柄（`ports/stm32-cubemx`）。禁用标准外设库；禁止直接写寄存器，除非官方 HAL 做不到，并且同一行或上一行写 `DZ-REG-OK: 原因`（check_deps P1）。

## 步骤
1. CubeMX 新建工程，按下面的**引脚标签约定**给引脚起 User Label：
   - `GPIO_<名>`（如 GPIO_LED）、`PWM_<名>`、`ENC_<名>_A/_B`、`UART_<名>_TX/_RX`、`ADC_<名>`
2. 必须的设置（ioc_import 会检查）：
| 规则 | 要求 |
|---|---|
| T1 | HAL 时基用 SysTick（pal_micros 读 SysTick） |
| N1 | NVIC 优先级分组 4（4 位抢占） |
| N2 | 用到的 UART/DMA/TIM 中断已使能 |
| N3 | SysTick 优先级（警告） |
| D1 | DMA stream 不冲突 |
| D2 | UART RX 为 Circular DMA，TX 为 Normal DMA（或无 DMA 用中断） |
| L1 | 标签符合约定 |
| U1 | main.c 有框架接缝，且没有与框架冲突的 HAL 回调 |
3. 生成代码到 `boards/<板>/cubemx/`，勾选 “Generate peripheral initialization as a pair of .c/.h” 可选；在 main.c 中：
```c
/* USER CODE BEGIN Includes */  #include "dz_cubemx.h"
/* USER CODE BEGIN 2 */         dz_cubemx_start();
/* USER CODE BEGIN 3 */         dz_cubemx_loop();
```
   USER CODE 区**只放这三行**（check_deps C1），业务逻辑写进子系统。
4. `python3 tools/ioc_import.py boards/<板>/cubemx/xxx.ioc --base boards/<旧板>/board.yaml --timer CTRL=TIM6 -o boards/<板>/board.yaml`，生成/合并 board.yaml（手写字段保留）。
5. `make ioc-check`、`make check`、`make BOARD=<板> APP=port_selftest` 编译自检固件并上板。

## 验证状态
- 【已实测】ioc_import 自检 9/9；`boards/stm32f407-skystar-cubemx` 合成工程交叉编译 motor_speed_demo（text 约 32 KB）、port_selftest、2026H_ball。
- 【未验证】该 .ioc 与 Core/ 是**手写合成样例**，没有用真实 CubeMX 打开/重新生成过；需用户用 CubeMX 打开确认后再当真。
- 【未验证】移植层上板行为（UART 循环 DMA 计数、定时器时钟推算、ADC）。F4 以外系列的 #ifdef 分支未编译。

## 参考来源
- ST UM1725《Description of STM32F4 HAL and low-layer drivers》（https://www.st.com/resource/en/user_manual/um1725-description-of-stm32f4-hal-and-lowlayer-drivers-stmicroelectronics.pdf；2026-10-28 从本机访问超时，地址为 ST 官方文档地址）。
- STM32CubeF4（https://github.com/STMicroelectronics/STM32CubeF4）、stm32f4xx-hal-driver v1.8.5、cmsis-device-f4 v2.6.11（`tools/fetch_stm32f4.sh` 固定 tag）。
- RoboMaster C 型例程（https://github.com/RoboMaster/Development-Board-C-Examples）：同为 CubeMX 生成 + USER CODE 调用用户代码的组织方式。
- UART 空闲中断 + 循环 DMA 收不定长数据：ST 社区常用做法，见 MaJerle/stm32-usart-uart-dma-rx-tx（https://github.com/MaJerle/stm32-usart-uart-dma-rx-tx）。
