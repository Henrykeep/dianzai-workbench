# Application 层

Application 只描述产品逻辑，并负责注册所需 Module、创建 FreeRTOS 任务。

- `application.c/.h`：整个框架的初始化与启动入口。
- `app_config.h`：带快速上手说明、硬件资源提示、统一功能开关和集中编译期检查的配置入口。
- `communication/`：集中保存串口等通信相关 Application。
- `communication/serial_communication/`：串口接收/发送业务和 ADC UART2 JustFloat 任务。
- `control/`：保存舵机、电机等执行机构的控制策略、状态机和任务业务循环。
- `control/servo_control/`：管理 PA23/PA24 双路舵机的独立目标角度、平滑移动、启停和故障停机。
- `input/matrix_keypad_input/`：管理 4×4 矩阵键盘扫描任务和静态事件队列。
- `menu/`：集中保存菜单相关 Application。
- `menu/custom_page/`：电赛自定义界面、按键动作和上电初始页面模板。
- `menu/display_menu/`：OLED/TFT 共用的页面、按键、波形和菜单任务。
- `menu/oled_menu/`：初始化 SSD1306 OLED 后端并接入共用菜单。
- `menu/tft_menu/`：初始化 ST7735S 1.8 寸 TFT 后端并接入共用菜单。
- `task/`：集中管理 Application 层任务名称、优先级、静态 TCB、静态栈和创建入口。
- `waveform/`：集中保存波形测量、映射和输出 Application。
- `waveform/waveform_measurement/`：组合 PA27/PB19 ADC、可选 PA27/PA21 COMP
  Capture 和 FFT 回退结果，同时发布两路独立的基础波形参数；第二路 ADC 的旧
  `PA21` API 名仅作为兼容别名保留。
- `waveform/waveform_mapping/`：订阅 PA27 单次测量结果，并自动映射到 PA15 DAC、AD9833 或 AD9850。
- `waveform/waveform_output/`：统一管理 PA15 DAC、AD9833 和 AD9850 输出后端。
- 应用层不得直接调用 TI DriverLib 或访问 GPIO 宏。
- 所有应用初始化都在调度器启动前完成。
- `ApplicationInit()` 具有一次性状态保护；失败时保存阶段并进入输出安全态。
- ADC 完整块直接通知波形测量累计，收齐配置点数后对完整窗口执行一次 FFT。
- Application 自建任务统一通过 `task/task_manager.c` 使用静态 TCB 和静态栈；
  任务业务循环仍保留在对应功能目录。
- UART2 采样使用订阅分发，串口 Application 不再反向依赖显示菜单或 FFT 消费者。

## 功能编译配置

`application/app_config.h` 中的 `APP_ENABLE_xxx` 只选择 Application，
不直接控制 Module 层。启用波形测量后，它内部按输入开关启动
ADC Sampling、FFT Analysis 和 Analog Capture。ADC UART2 JustFloat 由
`APP_ENABLE_ADC_JUSTFLOAT` 独立选择，并且必须同时启用 UART2。

不同 CCS Build Configuration 可以使用 `-DAPP_ENABLE_xxx=0/1` 覆盖默认值。
详细配置方法和约束见
[Application 编译配置使用指南](编译配置使用指南.md)。

## UART0 调试输出开关

UART0 调试输出具有一个总开关和每个 Application 文件自己的独立开关：

| 作用范围 | 宏定义 | 所在文件 |
|---|---|---|
| UART0 全部调试输出 | `APP_ENABLE_UART0_DEBUG` | `app_config.h` |
| 串口应用 | `SERIAL_COMMUNICATION_DEBUG_OUTPUT_ENABLED` | `communication/serial_communication/serial_communication.c` |
| 波形参数 | `WAVEFORM_MEASUREMENT_DEBUG_OUTPUT_ENABLED` | `waveform/waveform_measurement/waveform_measurement.c` |
| 波形映射 | `WAVEFORM_MAPPING_DEBUG_OUTPUT_ENABLED` | `waveform/waveform_mapping/waveform_mapping.c` |
| 波形输出 | `WAVEFORM_OUTPUT_DEBUG_OUTPUT_ENABLED` | `waveform/waveform_output/waveform_output.c` |
| 显示菜单 | `DISPLAY_MENU_DEBUG_OUTPUT_ENABLED` | `menu/display_menu/display_menu.c` |

总开关为 `0U` 时，所有模块调用 UART0 调试发送都会被静默忽略。总开关为 `1U`
时，还需要对应模块的独立开关为 `1U`，该模块才会输出提示。修改宏后必须重新编译
并烧录固件。

调试信息只放在初始化、错误、启停和用户配置变化等低频位置。ADC DMA 完成、DAC
查找表循环以及显示屏每帧刷新不会逐次打印，避免 UART0 轮询发送干扰实时任务。
