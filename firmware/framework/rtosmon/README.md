# rtosmon — RTOS 运行监测（CPU 负载 + 栈余量）  `v1.0.0`

纯逻辑，不依赖 RTOS 头文件。移植层把计数喂进 `g_rtosmon`，应用层读出来放进遥测（2026H_ball：`cpu_pm`、`stk_min_w`）。

- 接口：`rtosmon_feed_cpu / begin_stack / feed_stack / end_stack / cpu_permille / stack_min_words / stack_low`
- 自检：`rtosmon_selftest()`；tests/host/test_framework.c
- FreeRTOS 喂数据：`ports/stm32-cubemx/dz_freertos.c`（`uxTaskGetSystemState` + 空闲任务运行时间）；任务模板见 `ports/stm32-cubemx/freertos_task_template.c`。用法见 docs/11-中断与实时.md 的 FreeRTOS 一节。
- 裸机板：没人喂，读到 `RTOSMON_NA`（0xFFFF），上位机显示“无”。

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：负载换算（含 32 位回绕）、栈最小值与任务名、半轮扫描不外泄。
- **已实测（交叉编译）**：stm32f407-bldc-freertos-cubemx/2026H_ball 能编过、链接进 FreeRTOS。
- **【未测】上板**：CPU 负载和栈余量的读数是否正确，需要在真板上对照 FreeRTOS `vTaskGetRunTimeStats` / 调试器 RTOS 视图核对。

## 参考来源
- FreeRTOS 官方文档：uxTaskGetSystemState、uxTaskGetStackHighWaterMark、Run Time Statistics（思路，非代码）。
