# st_hal_conf —— ST HAL 的 hal_conf 模板（BSD-3-Clause）

Source: github.com/STMicroelectronics/stm32f1xx-hal-driver@7bda310 Inc/stm32f1xx_hal_conf_template.h（tag v1.1.9）
Source: github.com/STMicroelectronics/stm32f4xx-hal-driver@b6f0ed3 Inc/stm32f4xx_hal_conf_template.h（tag v1.8.5）

（Copyright STMicroelectronics；`LICENSE` 为 HAL 仓库 LICENSE.md 原文，F1/F4 两仓库除年份外一致）

- 搬了什么：两个 hal_conf 模板原文（只在首行加 Source 注释）。
- 为什么：`tools/gen_core.py` 合成 Core 时要复制 hal_conf 模板；随仓库带上，从零新建（生成 .ioc + 合成 Core）不依赖本机 CubeMX 或 `make fetch` 拉的 HAL。
- 优先用本目录；没有该系列时退回 `third_party/stm32<族>xx-hal-driver/Inc/`。新增系列：同样搬模板并在此登记。
