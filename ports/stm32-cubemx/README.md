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
只有 make 构建带 `-DDZ_NVM_KB`（BOARD_NVM_DEFS）；Keil/CCS 工程不带 = ENOTSUP，不影响开机。

board.yaml `mcu.nvm_kb` > 0 时 `pal_nvm_*` 可用：F1 = Flash 末尾（页 1 KB，≥256 KB 型号 2 KB），F4 = 扇区 1..3（0x08004000 起，nvm_kb 只能 32/48；仓库里的 F4 链接脚本把 `.text` 放到保存区之后）。用你自己 CubeMX 生成的链接脚本时要照着留出这块，否则运行时检查到重叠会一直返回 ENOTSUP（不会擦到代码）。擦除期间 CPU 停顿（F4 扇区约 0.3 s），应用只在停车/急停时写。[编译]
