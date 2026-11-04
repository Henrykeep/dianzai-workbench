# Application Task Manager

`task_manager.c/.h` 集中管理 Application 层 FreeRTOS 任务的名称、优先级、
静态 TCB、静态栈和创建入口。各功能目录继续保存任务的业务循环，避免 Task
Manager 依赖菜单、波形或串口的私有状态。

| Task ID | FreeRTOS 名称 | 优先级 | 栈深度 |
|---|---|---:|---:|
| `APPLICATION_TASK_SERIAL_UART1_RX` | `UART1Rx` | 2 | 128 words |
| `APPLICATION_TASK_SERIAL_UART2_RX` | `UART2Rx` | 2 | 128 words |
| `APPLICATION_TASK_SERIAL_UART3_RX` | `UART3Rx` | 2 | 128 words |
| `APPLICATION_TASK_ADC_JUSTFLOAT` | `ADC2Vofa` | 1 | 192 words |
| `APPLICATION_TASK_SERVO_CONTROL` | `ServoControl` | 2 | 192 words |
| `APPLICATION_TASK_MOTOR_CONTROL` | `MotorControl` | 2 | 192 words |
| `APPLICATION_TASK_MATRIX_KEYPAD` | `MatrixKeypad` | 2 | 128 words |
| `APPLICATION_TASK_MPU6050_INPUT` | `MPU6050Input` | 2 | 256 words |
| `APPLICATION_TASK_PA27_THRESHOLD_TRIGGER` | `PA27Trigger` | 2 | 416 words |
| `APPLICATION_TASK_WAVEFORM_MEASUREMENT` | `WaveMeasure` | 2 | 416 words |
| `APPLICATION_TASK_DAC_REFILL` | `DACRefill` | 3 | 128 words |
| `APPLICATION_TASK_DISPLAY_MENU` | `OLEDMenu` 或 `TFTMenu` | 1 | 320 words |

UART1～UART3、JustFloat、舵机、电机、矩阵键盘、MPU6050、阈值触发和波形测量
任务关闭时，对应的静态
TCB 与任务栈不会分配 SRAM。UART2 关闭时，Module 层的 `FFTAnalysis` 异步任务和三份 64 点
UART2 缓冲区也会一同裁剪；ADC 频谱仍继续使用共享 FFT 工作区。

## 任务函数位置

点击下表中的函数名可以直接跳转到任务循环的实现位置。修改任务实际执行内容时，
应修改对应业务文件中的任务函数；任务名、优先级和栈深度则在
[`task_manager.c`](task_manager.c) 中统一修改。

| FreeRTOS 名称 | 任务函数位置 | 主要内容 |
|---|---|---|
| `UART1Rx` | [`SerialCommunicationUART1ReceiveTask()`](../communication/serial_communication/serial_communication.c#L994) | 接收并解析 UART1 协议帧 |
| `UART2Rx` | [`SerialCommunicationUART2ReceiveTask()`](../communication/serial_communication/serial_communication.c#L1018) | 接收 UART2 ADC 采样帧并通知订阅者 |
| `UART3Rx` | [`SerialCommunicationUART3ReceiveTask()`](../communication/serial_communication/serial_communication.c#L1042) | 解析通用样本、CRLF 文本行以及 21 条数据命令的准备/收数状态机 |
| `ADC2Vofa` | [`ADCJustFloatTask()`](../communication/serial_communication/adc_justfloat.c#L205) | 将 ADC 数据封装为 JustFloat 并通过 UART2 发送 |
| `ServoControl` | [`ServoControlTask()`](../control/servo_control/servo_control.c#L275) | 单个任务每 20 ms 独立更新 PA23/PA24 两路舵机；是否启动和自动往返由配置决定，当前默认均关闭 |
| `MotorControl` | [`TB6612ControlTask()`](../control/motor_control/motor_control.c#L252) | 单个任务每 10 ms 更新 TB6612 两路电机，执行平滑调速、换向保护和 STBY 管理 |
| `MatrixKeypad` | [`MatrixKeypadInputTask()`](../input/matrix_keypad_input/matrix_keypad_input.c#L181) | 每 10 ms 扫描 4×4 矩阵键盘，并把防抖后的按下/释放事件写入静态队列 |
| `MPU6050Input` | [`MPU6050InputTask()`](../input/mpu6050_input/mpu6050_input.c) | 周期读取 MPU6050；设备未就绪时每 500 ms 重试，DMP 可选 |
| `PA27Trigger` | [`PA27ThresholdTriggerTask()`](../waveform/pa27_threshold_trigger/pa27_threshold_trigger.c) | 等待 PA27 振幅超过阈值，采集指定窗口并保存到 Flash 波形槽位 |
| `WaveMeasure` | [`WaveformMeasurementTask()`](../waveform/waveform_measurement/waveform_measurement.c#L1139) | 完成波形测量、FFT 结果处理和波形分类 |
| `DACRefill` | [`DACOutputRefillTask()`](../../modules/dac/dac_output.c) | 接收 DAC 中断通知，在任务上下文生成并提交下一块1024点固定速率波形数据 |
| `OLEDMenu` / `TFTMenu` | [`DisplayMenuTask()`](../menu/display_menu/display_menu.c#L1929) | 轮询按键并处理自定义页、菜单、波形和频谱页面；TFT 全屏刷新需要较大任务栈 |

Module 层内部任务的位置：

- [`FFTAnalysisTask()`](../../modules/fft/fft_analysis.c#L477)：仅在 UART2 开启时处理 UART2 FFT 帧。
- [`BlinkyTask()`](../../modules/led/blinky.c#L49)：周期控制 LED，当前启动流程未启用。

`FFTAnalysis`、`Blinky` 等 Module 内部工作任务继续由对应 Module 管理。当前
FreeRTOS 配置 `configUSE_TIMERS=0`，因此内核只创建 `IDLE`，不会创建
`Tmr Svc`；若以后启用软件定时器，再把 Timer Service 的栈和队列资源计入预算。

## 查看任务栈余量

`ApplicationTaskGetMinimumFreeStackWords(task)` 返回指定任务启动以来从未使用过的
最小栈余量，单位是 words。显示任务每秒自动采样一次，可直接调用
`DisplayMenuGetMinimumFreeStackWords()`，或在调试器表达式窗口观察其返回值。
返回 `0` 表示任务尚未创建、配置已关闭或没有可用余量。建议在 FFT、TFT 全屏
刷新等最深调用路径至少执行一次后再读取，不要仅以上电空闲时的数值缩减任务栈。

Application 层新增任务时，应先在 `ApplicationTask_e` 中登记，并在
`task_manager.c` 中配置任务资源，再由对应 Application 调用
`ApplicationTaskCreate()`。不要在其他 Application 源文件中直接调用
`xTaskCreate()` 或 `xTaskCreateStatic()`。

电机控制任务的静态 TCB 和栈只在 `APP_ENABLE_MOTOR_CONTROL`（或兼容的
`APP_ENABLE_TB6612_CONTROL`）开启时分配；任务业务循环仍保留在
`application/control/motor_control/`，Task Manager 不直接依赖 TB6612 Module。
