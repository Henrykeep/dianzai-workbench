# Module 层

Module 将 BSP 能力组合成 Application 可复用的功能服务和通用算法。

- Module 不直接调用 TI DriverLib。
- 公共接口不暴露 DriverLib 或 SysConfig 类型。
- 使用静态实例、静态互斥锁和静态任务缓冲，尽量避免动态内存。
- `adc/` 提供 PA27/ADC0.0、PB19/ADC1.6 的一次性 DMA、阈值触发、双路同步采集和毫伏换算；`PA21` 仅作为第二路 ADC 的旧 API 名保留。
- `capture/` 提供 PA27/COMP0、PA21/COMP2 两路独立的 Timer Capture、周期和频率换算；PA21 捕获引脚不是当前第二路 ADC 引脚。
- `dac/` 提供线程安全的 PA15 静态电压和连续 DMA 波形输出；高优先级回填任务由 Waveform Output Application 登记并创建。
- `dds/` 提供通用 DDS 状态、AD9833 与 AD9850 后端及默认设备便捷输出服务。
- `fft/` 提供最大 2048 点 CMSIS-DSP Q15 FFT，以及 PA27、PB19、UART2 本地 FFT 与 UART3 外部频谱的独立结果快照。
- `button/` 统一处理 PA18/PB21 的有效电平、30 ms 防抖和长短按事件。
- `filter/` 提供三点中值滤波和带 Q/R 参数的一维卡尔曼滤波静态实例。
- `i2c/` 使用静态 FreeRTOS 互斥锁保护阻塞式纯写和重复起始写后读事务。
- `menu/` 提供与业务无关的页面、条目、子菜单、滚动和动作回调。
- `matrix_keypad/` 提供 4×4 矩阵键盘逐行扫描、16 键独立防抖和按下/释放位图。
- `display/` 为菜单和波形提供 OLED/TFT 通用的 128×64 逻辑画布。
- `oled/` 中 `oled_display` 管理默认显示实例，`oled` 提供 SSD1306 驱动、帧缓冲、5×7 字体和绘图接口。
- `tft/` 提供 ST7735S 驱动、行式 RGB565 转换和通用显示适配。
- `pid/` 提供浮点位置式 PID、输出/积分限幅和条件积分抗饱和。
- `led/` 还提供使用静态 FreeRTOS 任务的 Blinky 轮转演示。
- `pwm/` 将频率、占空比或微秒脉宽换算为定时器计数，并提供 PA23/PA24 双通道线程安全控制和 PA23 便捷输出接口。
- `servo/` 在 PWM Module 上提供 PA23/PA24 双路 50 Hz 舵机角度、脉宽和启停控制。
- `tb6612/` 提供双路电机正反转、0～100% PWM、滑行/制动和 STBY 控制。
- `serial/` 通过静态 FreeRTOS Stream Buffer/队列将 UART 接收中断或 DMA 与应用任务解耦。
- `spi/` 使用设备锁和 SPI1 共享总线锁保护 AD9833、AD9850、TFT 的完整事务。
- `waveform/` 提供 128 点环形缓冲、量程映射、网格和连续曲线绘制。

## 使用指南索引

| Module | 文档 |
|---|---|
| ADC | [ADC使用指南](adc/ADC使用指南.md)、[ADC Sampling使用指南](adc/ADC采样使用指南.md)、[ADC同步采集使用指南](adc/ADC同步采集使用指南.md) |
| Capture | [Capture使用指南](capture/Capture使用指南.md)、[Analog Capture使用指南](capture/AnalogCapture使用指南.md) |
| Button | [Button使用指南](button/Button使用指南.md) |
| DAC | [DAC使用指南](dac/DAC使用指南.md) |
| DDS | [DDS使用指南](dds/DDS使用指南.md)、[AD9850使用指南](dds/AD9850使用指南.md) |
| FFT | [FFT使用指南](fft/FFT使用指南.md)、[FFT Analysis使用指南](fft/FFT分析使用指南.md) |
| Filter | [三点中值滤波使用指南](filter/三点中值滤波使用指南.md)、[卡尔曼滤波使用指南](filter/卡尔曼滤波使用指南.md) |
| I2C | [I2C使用指南](i2c/I2C使用指南.md) |
| LED | [LED使用指南](led/LED使用指南.md)、[Blinky使用指南](led/Blinky使用指南.md) |
| Menu | [Menu使用指南](menu/Menu使用指南.md) |
| Matrix Keypad | [4×4矩阵键盘使用指南](matrix_keypad/矩阵键盘使用指南.md) |
| OLED | [OLED使用指南](oled/OLED使用指南.md) |
| TFT | [TFT使用指南](tft/TFT使用指南.md) |
| PID | [PID使用指南](pid/PID使用指南.md) |
| PWM | [PWM使用指南](pwm/PWM使用指南.md)、[PWM Output使用指南](pwm/PWMOutput使用指南.md) |
| Servo | [Servo使用指南](servo/Servo使用指南.md) |
| TB6612 | [TB6612使用指南](tb6612/TB6612使用指南.md) |
| Serial | [Serial使用指南](serial/Serial使用指南.md) |
| SPI | [SPI使用指南](spi/SPI使用指南.md) |
| Waveform | [Waveform使用指南](waveform/Waveform使用指南.md) |
