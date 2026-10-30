# STM32 CubeMX 移植层（推荐）  `v1.0.0`

CubeMX 是唯一配置源，本层只包装 CubeMX 生成的句柄（htimX/huartX/hadcX），与系列无关。接缝：main.c 的 USER CODE 里 `dz_cubemx_start()` / `dz_cubemx_loop()`。前提由 tools/ioc_import.py 检查（SysTick 时基、优先级分组 4、RX 循环 DMA…）。

- 接口：实现 pal.h；`dz_cubemx.h`
- 自检：`apps/port_selftest`
- 版本规则：见 docs/03-模块三件套与版本.md（删改声明 = MAJOR，新增 = MINOR，iface_hash 强制）

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：交叉编译通过（合成 CubeMX 样例工程，F407）
- **未验证**：**未上板**；样例工程是手写合成的，**未经 CubeMX 真实生成验证**；F4 以外系列只在代码里做了 #ifdef 预留，**未编译验证**

## 参考来源
- ST 官方 HAL 用户手册 UM1725（F4）；CubeMX USER CODE 保留规则

## I2C / SPI（1.2.0）
- 使用 CubeMX 生成的 `hi2cN` / `hspiN` 句柄，阻塞调用。SPI 片选由本层软件控制：CubeMX 里要把 CS 引脚配成 GPIO_Output，初始电平为高。
- CubeMX 没启用 I2C/SPI 模块（hal_conf 里没有对应的 `HAL_xxx_MODULE_ENABLED`）时，调用返回 ENOTSUP。**[编译]**，未上板。

## GPIO 边沿中断（1.3.0，PAL 1.2.0）
1. CubeMX 里把引脚设成 `GPIO_EXTIx`，GPIO Mode 选 *External Interrupt Mode with Rising/Falling edge trigger detection*；
2. NVIC 里勾上对应的 `EXTI line x interrupt`（CubeMX 会在 stm32xxxx_it.c 生成 `EXTIx_IRQHandler`）；
3. board.yaml 里照常写 `dir: in`，应用里 `pal_gpio_irq_attach(RES_GPIO_xxx, PAL_EDGE_BOTH, cb, ctx)`。

本层提供 `HAL_GPIO_EXTI_Callback`（G0/C0/L5/U5/H5 提供 Rising/Falling 两个回调）。工程里已有自己的回调：编译加 `-DDZ_CM_NO_EXTI_CALLBACK`，
在你的回调里调用 `dz_cm_gpio_exti(GPIO_Pin)`。同号引脚共用一条 EXTI 线（PA3 与 PB3 不能同时挂，返回 DZ_EBUSY）。【编译】未上板。

## 掉电保存（1.7.0）
Keil：`tools/keil_inject.py <工程>.uvprojx --board <板> --app <应用>` 会同时加 `DZ_NVM_KB/DZ_FLASH_KB` 宏、把 Linker→Scatter File 设成 `boards/<板>/keil/dz_nvm.sct`（tools/gen_ide_nvm.py 按 nvm_kb 生成：F1 程序区截短，F4 扇区 0 只放向量、程序从保存区之后开始；保存区是 EMPTY 域，下载不擦）并关掉“Use Memory Layout from Target Dialog”。armclang 下运行时核对 `Image$$ER_DZ_NVM$$ZI$$Base`，没用这份 .sct 链接直接报错。[未测] Keil 里没编译过。

board.yaml `mcu.nvm_kb` > 0 时 `pal_nvm_*` 可用：F1 = Flash 末尾（页 1 KB，≥256 KB 型号 2 KB），F4 = 扇区 1..3（0x08004000 起，nvm_kb 只能 32/48；仓库里的 F4 链接脚本把 `.text` 放到保存区之后）。用你自己 CubeMX 生成的链接脚本时要照着留出这块，否则运行时检查到重叠会一直返回 ENOTSUP（不会擦到代码）。擦除期间 CPU 停顿（F4 扇区约 0.3 s），应用只在停车/急停时写。[编译]

## DAC（1.9.0，PAL 1.7.0）
- CubeMX 里开 DAC（F4/F1 叫 DAC → 句柄 hdac；H7/G4 叫 DAC1 → hdac1），输出脚标签 `DAC_<名>`（PA4 = 通道 1，PA5 = 通道 2），ioc_import 生成 `dac:` 资源；hal_conf 要有 `HAL_DAC_MODULE_ENABLED`，没有会 #error 提示。
- `pal_dac_write` 第一次调用时 `HAL_DAC_Start`，之后 `HAL_DAC_SetValue`（12 位/8 位右对齐）。
- F103C8/CB、F401/F411/F412 没有 DAC：validate_board 拒绝写 `dac:`，`pal_dac_write` 返回 DZ_ENOTSUP。
- 【编译】只在 F4（skystar-cubemx 样例）交叉编译过；H7/G4 句柄命名按 CubeMX 规则推出，未编译（仓库没有 H7 HAL）。

## ADC 块采样硬件路径（1.10.0）

board.yaml `adc[].block: {timer: TIM2}`：F4 可用 TIM2/3/8，F1 TIM3/8（ADC 规则组 TRGO 触发源）。CubeMX 里要给该 ADC 配 DMA（Normal，半字）并生成 DMA IRQ；定时器开 Base 即可，PSC/ARR 由移植层按采样率改写。完成判定轮询 DMA 剩余计数，不定义 HAL_ADC_ConvCpltCallback。【编译】未上板。

## 三相 PWM（1.11.0，PAL 1.8.0）
`pal_pwm3_set / pal_pwm3_check`：UDIS 暂停更新事件后写三路 CCR、再清 UDIS（靠 CubeMX 的 Output compare preload），pal_pwm3_check 读 CR1.CMS。比较值按中心对齐算（周期 = 2·LOAD/ARR）。【编译】未上板；样例板没有加 pwm3（要先在 CubeMX/SysConfig 里配三路中心对齐 PWM）。
