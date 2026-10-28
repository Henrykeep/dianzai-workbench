# STM32F4 HAL 移植层（board.yaml 驱动初始化）  `v1.0.0`

由 board.yaml 生成的表在运行时调用 HAL 完成时钟/引脚/DMA 初始化，**不需要 CubeMX**。F4 系列板卡共用：天空星 F407、RoboMaster C 型。正式推荐流程是 stm32-cubemx；本层保留用于快速验证和无 CubeMX 环境。

- 接口：实现 pal.h；`main_stm32f4.c` 提供 main()
- 自检：`apps/port_selftest`
- 版本规则：见 docs/03-模块三件套与版本.md（删改声明 = MAJOR，新增 = MINOR，iface_hash 强制）

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：交叉编译通过（motor_speed_demo、2026H_ball、port_selftest；含 dji-rm-c 临时 HSE 编译）
- **未验证**：**未上板**

## 参考来源
- STM32CubeF4 HAL 官方 API 与参考手册 RM0090
