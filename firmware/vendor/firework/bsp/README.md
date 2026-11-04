# BSP 层

BSP 是唯一允许直接使用 TI DriverLib、SysConfig 生成宏和芯片寄存器的代码层。

## 文档索引

| 内容 | 使用指南 |
| --- | --- |
| BSP 初始化入口与分层约束 | [BSP初始化指南.md](BSP初始化指南.md) |
| ADC0/ADC1 单通道一次性 N 点 DMA | [adc/ADC使用指南.md](adc/ADC使用指南.md) |
| COMP0/COMP2 事件与双定时器周期捕获 | [capture/Capture使用指南.md](capture/Capture使用指南.md) |
| DAC0 模拟电压输出 | [dac/DAC使用指南.md](dac/DAC使用指南.md) |
| LED 与按键 GPIO | [gpio/GPIO使用指南.md](gpio/GPIO使用指南.md) |
| I2C0/I2C1 阻塞写读传输 | [i2c/I2C使用指南.md](i2c/I2C使用指南.md) |
| TIMG7 CCP0/CCP1 双路 PWM 输出 | [pwm/PWM使用指南.md](pwm/PWM使用指南.md) |
| TIMA1 双路 TB6612 PWM 与方向 GPIO | [tb6612/TB6612板级使用指南.md](tb6612/TB6612板级使用指南.md) |
| SPI1 DDS 和 SPI0 TFT 控制总线 | [spi/SPI使用指南.md](spi/SPI使用指南.md) |
| UART0轮询、UART1～UART3发送/接收与 DMA | [uart/UART使用指南.md](uart/UART使用指南.md) |

## 目录职责

- `bsp.c/.h`：板级初始化、故障安全关断、启动延时和主 Flash 操作。
- `adc/`：TIMG0 触发 ADC0/ADC1；ADC0 采集 PA27，ADC1 采集 PB19/ADC1.6，
  DMA_CH5/6 分别搬运；旧 PA21 ADC 名只作为上层兼容别名。
- `capture/`：把 PA27/COMP0 和 PA21/COMP2 边沿分别送入 TIMG12/TIMG6。
- `dac/`：DAC0 的 PA15 模拟输出、12位固定值，以及Sample Timer + DMA_CH0查找表输出。
- `gpio/`：LED、PA18/PB21 按键、矩阵键盘、TFT PB1/PB4 和 AD9850 PA1 控制引脚封装。
- `i2c/`：I2C Controller 注册、超时轮询发送和错误恢复。
- `pwm/`：TIMG7 CCP0/CCP1 的共享周期、独立比较值、影子更新和输出启停封装。
- `tb6612/`：TIMA1 PA17/PA16 双路 PWM、五路方向/STBY GPIO 和故障安全停机。
- `spi/`：SPI1 上 AD9833 16 位与 AD9850 8 位串行事务、SPI0 TFT 8 位轮询发送，
  并手动控制 FSYNC/FQ_UD/CS。
- `uart/`：UART 注册、阻塞发送和接收中断分发。
- 上层不得直接包含 `ti_msp_dl_config.h`。

新增外设时，先在 `blink_led.syscfg` 中完成配置，再在本层提供不暴露硬件细节的接口。
