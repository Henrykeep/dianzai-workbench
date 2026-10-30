# 05 STM32 CubeMX 工作流（推荐）

> 标注约定：**【已实测】** = 本仓库在 PC 上用测试/编译实际跑过（2026-10-28，Asia/Shanghai）；**【未验证】** = 设计意图或推断，尚未在真实硬件上做实验。实验是检验真理的唯一标准——【未验证】的内容上板前不要当结论。

**STM32 只用 CubeMX + HAL**：CubeMX 的 .ioc 是唯一配置源（时钟、引脚、DMA、中断），框架只包装它生成的句柄（`ports/stm32-cubemx`）。禁用标准外设库；禁止直接写寄存器，除非官方 HAL 做不到，并且同一行或上一行写 `DZ-REG-OK: 原因`（check_deps P1）。

## 步骤
1. CubeMX 新建工程，按下面的**引脚标签约定**给引脚起 User Label：
   - `GPIO_<名>`（如 GPIO_LED）、`PWM_<名>`、`ENC_<名>_A/_B`、`UART_<名>_TX/_RX`、`ADC_<名>`
2. 必须的设置（ioc_import 会检查）：
| 规则 | 要求 |
|---|---|
| T1 | HAL 时基 SysTick（裸机默认，pal_micros 读 SysTick）或 TIMx（FreeRTOS 工程推荐，pal_micros 读该 TIM 计数器；board.yaml `config_source.hal_timebase` 必须与 .ioc 一致）；识别不了才报错 |
| N1 | NVIC 优先级分组 4（4 位抢占） |
| N2 | 用到的 UART/DMA/TIM 中断已使能 |
| N3 | SysTick 优先级（警告） |
| D1 | DMA stream 不冲突 |
| D2 | UART RX 推荐 Circular DMA；Normal DMA（收满在回调里重新启动）和无 DMA（逐字节中断，115200 时每字节约 87 µs 一次中断）可用但报警告 |
| P1 | 电机 PWM 低于 5 kHz 报警告（可闻噪声、电流纹波；名字含 SERVO 的不查） |
| L2 | 用到的外设引脚没有 User Label 报警告 |
| L1 | 标签符合约定 |
| U1 | main.c 有框架接缝，且没有与框架冲突的 HAL 回调 |
3. 生成代码到 `boards/<板>/cubemx/`，勾选 “Generate peripheral initialization as a pair of .c/.h” 可选；在 main.c 中：
```c
/* USER CODE BEGIN Includes */  #include "dz_cubemx.h"
/* USER CODE BEGIN 2 */         dz_cubemx_start();
/* USER CODE BEGIN 3 */         dz_cubemx_loop();
```
   USER CODE 区**只放这三行**（check_deps C1），业务逻辑写进子系统。

   **FreeRTOS 工程**（.ioc 里有 FREERTOS，board.yaml `config_source.rtos: freertos`；Makefile 自动加内核、按 CPU 选 port、heap_4、cmsis_os2.c）：osKernelStart() 之后 main 的 while 不再运行，所以：
```c
/* USER CODE BEGIN 5 */   (void)argument; for(;;) { dz_cubemx_loop(); osDelay(1); }   // StartDefaultTask
```
   **HAL 时基为 TIMx 时**，CubeMX 在 main.c 生成 `HAL_TIM_PeriodElapsedCallback`，框架不能再定义它，改为在里面转发：
```c
/* USER CODE BEGIN Callback 1 */   dz_cubemx_tim_callback(htim);
```
   这两种写法也属于 C1 允许的接缝；ioc_import `--check` 会检查它们在不在（U1）。

### UART 接收的三种模式（移植层运行时按句柄自动选择）
| .ioc 设置 | 行为 | 状态 |
|---|---|---|
| RX DMA Circular | 空闲中断 + 读 DMA 计数，不丢字节 | 推荐 |
| RX DMA Normal | 收满或空闲后在回调里重新 `HAL_UARTEx_ReceiveToIdle_DMA`，重启间隙可能丢字节 | 警告 |
| 无 RX DMA | 1 字节 `HAL_UART_Receive_IT` 进环形缓冲 | 警告，仅低波特率 |
4. `python3 tools/ioc_import.py boards/<板>/cubemx/xxx.ioc --base boards/<旧板>/board.yaml --timer CTRL=TIM6 -o boards/<板>/board.yaml`，生成/合并 board.yaml（手写字段保留）。
5. `make ioc-check`、`make check`、`make BOARD=<板> APP=port_selftest` 编译自检固件并上板。

## 已经有自己的 CubeMX/Keil 工程？直接导入（不用改 .ioc、不用改代码）

```sh
python3 tools/import_project.py <你的工程目录> --app car_2wd          # 先看报告
python3 tools/import_project.py <你的工程目录> --app car_2wd --accept-repair   # main.c 标记坏了时，看过 diff 再确认
make BOARD=<目录名> APP=car_2wd
```

- 板名取自目录名（自动转成合法名字）；原工程**一个字节都不改**，复制到 `boards/<名>/cubemx/`。
- **标签不用按约定改**：自动按引脚功能生成 `boards/<名>/aliases.yaml`（如 `AIN1 → GPIO_MOTOR_A_IN1`、PWMA/PWMB → MOTOR_A/B）。猜错就改这张表，`.ioc` 不动。
- **节拍定时器 CTRL**：先找 .ioc 里已开中断、没接引脚的定时器；没有就挑空闲的（TIM6/7/5/4…），由工作台自己初始化（`timer.self_init`），不用回 CubeMX 加。
- **你写在 main.c / freertos.c USER CODE 里的代码**：整块原样搬到 `user_code/from_core_user_code.c.txt`（不编译、不删），你的 APP/HARDWARE 源码备份在 `user_code/orig/`；钩子（`dz_cubemx_start/loop/tim_callback`）只插在 USER CODE 区。FreeRTOS 工程钩子放进 StartDefaultTask。
- **USER CODE 标记被改坏**（例如 while(1) 写进了 USER CODE 3 而 BEGIN WHILE 没了）：停下、打印修复 diff，确认后加 `--accept-repair`。
- **Keil(MDK) 生成的工程**没有 `*_FLASH.ld`/gcc 启动文件：按芯片从 `ports/stm32-cubemx/ld/` 模板补链接脚本，启动文件用 CMSIS gcc 模板。
- 报告分三类：动手改 / 确认 / 上板观察；`--report x.json` 输出机器可读结果。p2 Car_Mode1021：动手改 0、确认 2、观察 1；p1 Bldc：动手改 0、确认 1。
- 回归：`make check` 跑 `tools/test_import_project.py`，用你原样的 p2/p1 工程（`tools/testdata/real/projects/`）导入，“动手改/确认/观察”条数超过 `import_baseline.json` 就失败。
- `make` 写成 `PROJECT=` 会直接报错提示用 `APP=<目录>`。

## 串口接收：推荐 Circular DMA（IT 为兜底）
移植层按 CubeMX 配置自动选模式（ioc_import 会报告是哪种）：
| CubeMX 配置 | 移植层行为 | 建议 |
|---|---|---|
| RX DMA，Mode = **Circular** | DMA 一直跑，主循环按 NDTR 取新字节，零中断开销 | **推荐** |
| RX DMA，Mode = Normal | 收满或空闲后自动重启 DMA，重启间隙依赖数据寄存器缓冲 | 可用（用户原工程就是这样） |
| 无 RX DMA | 每字节一次中断（1 字节 IT） | 兜底；低流量（如 QD4310 每 10 ms 一帧 10 字节）完全够用 |

CubeMX 里设 Circular：Connectivity → USARTx → **DMA Settings** → Add → 选 `USARTx_RX` → Mode 选 **Circular**，Data Width 两边都是 Byte，Increment Address 只勾 Memory；NVIC Settings 里勾上 USARTx global interrupt（空闲中断要用）。TX 保持 Normal。改完 Generate Code，再跑 `make ioc-check`。
- 【已实测（仅编译）】F103 合成工程两路 RX 已改 Circular、交叉编译通过。【未验证】上板。

## 验证状态
- 【已实测】ioc_import 自检 9/9；`boards/stm32f407-skystar-cubemx` 合成工程交叉编译 motor_speed_demo（text 约 32 KB）、port_selftest、2026H_ball。
- 【未验证】该 .ioc 与 Core/ 是**手写合成样例**，没有用真实 CubeMX 打开/重新生成过；需用户用 CubeMX 打开确认后再当真。
- 【已实测（仅编译）】`boards/stm32f103c8t6-car-cubemx`（F1，基于用户 USART.ioc，无 RX DMA）与 `boards/stm32f407-bldc-freertos-cubemx`（F4 + FreeRTOS + TIM1 时基，基于用户 Bldc.ioc）交叉编译 car_2wd；ioc-check 0 处不一致。两者 Core/ 同样是手写合成。
- 【未验证】移植层上板行为（UART 循环 DMA 计数、定时器时钟推算、ADC）。F4 以外系列的 #ifdef 分支未编译。

## 参考来源
- ST UM1725《Description of STM32F4 HAL and low-layer drivers》（https://www.st.com/resource/en/user_manual/um1725-description-of-stm32f4-hal-and-lowlayer-drivers-stmicroelectronics.pdf；2026-10-28 从本机访问超时，地址为 ST 官方文档地址）。
- STM32CubeF4（https://github.com/STMicroelectronics/STM32CubeF4）、stm32f4xx-hal-driver v1.8.5、cmsis-device-f4 v2.6.11（`tools/fetch_stm32f4.sh` 固定 tag）。
- RoboMaster C 型例程（https://github.com/RoboMaster/Development-Board-C-Examples）：同为 CubeMX 生成 + USER CODE 调用用户代码的组织方式。
- UART 空闲中断 + 循环 DMA 收不定长数据：ST 社区常用做法，见 MaJerle/stm32-usart-uart-dma-rx-tx（https://github.com/MaJerle/stm32-usart-uart-dma-rx-tx）。
