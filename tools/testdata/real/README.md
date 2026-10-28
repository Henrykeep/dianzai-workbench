# 真实 CubeMX 工程（用户提供）

| 文件 | 原工程 | 芯片 | 说明 |
|---|---|---|---|
| bldc_f407vet6.ioc | Bldc.ioc（CubeMX 6.16.0） | STM32F407VET6 | FreeRTOS、TB6612 双电机、双编码器、8 路灰度、4 按键 |
| usart_f103c8t6.ioc | USART.ioc（CubeMX 6.15.0） | STM32F103C8T6 | 双电机、双编码器、8 路循迹、软件 I2C OLED、双串口 DMA |

用途：`tools/test_ioc_import.py` 的回归样本，`*.expected.yaml` 是对照 .ioc 逐行人工核对后的期望导入结果。

内容只有引脚/时钟/外设配置，不含路径、账号、个人信息，已确认可入库。
如果以后仓库要公开且不想带上自己的工程配置：把本目录加入 `.gitignore`，并在 CI 里跳过 test_ioc_import 的 real/ 部分。
