# ports/mspm0-driverlib（0.1.0）

MSPM0（天猛星 MSPM0G3507）的 PAL 实现：**SysConfig + DriverLib**。SysConfig 生成的 `ti_msp_dl_config.{c,h}` 是唯一配置源，
本层只包装其中的实例宏，只调 DriverLib。

| 资源 | SysConfig 实例名约定 | 实现 |
|---|---|---|
| gpio | GPIO 组 `GPIO_<名>`，组内引脚名 `PIN` → `GPIO_<名>_PORT` / `GPIO_<名>_PIN_PIN` | DL_GPIO_set/clear/read/togglePins |
| pwm | PWM 实例 `PWM_<定时器>`（如 PWM_TIMG0），通道 = CCP 序号 | 改比较值；频率在 SysConfig 定 |
| encoder (hw) | QEI 实例 `ENC_<名>`（G3507 只有 TIMG8） | 16 位计数扩展到 32 位 |
| encoder (gpio_isr) | GPIO 组 `ENC_<名>`，引脚 `A` / `B`，双边沿中断 | GROUP1 中断里格雷码表 4 倍频 |
| uart | UART 实例 `UART_<名>` | RX/TX 中断 + 环形缓冲（无 DMA） |
| timer | Timer 实例 `TIMER_<名>`，Periodic + ZERO 中断，`_CLK_FREQ` 整 MHz | 运行时改装载值 |
| adc | — | 未实现（返回 DZ_ENOTSUP，有 adc 资源时编译报错） |
| i2c / spi | — | 未实现（返回 DZ_ENOTSUP，board check 警告）；IMU 请用 UART 姿态模块（apps/imu_module + proto/dzimu） |

时基：SysTick 1 ms（本层配置）。`main()` 在 `main_mspm0.c`（SysConfig 不生成 main）。

**验证状态**：【已实测】car_2wd 交叉编译通过。【未验证】全部上板行为；`boards/mspm0g3507-tianmengxing/syscfg/` 下的配置是合成样例。
