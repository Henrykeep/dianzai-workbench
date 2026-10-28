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
