# ports/mspm0-driverlib（0.4.0）

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
| 看门狗 | 不用在 SysConfig 配，`pal_wdg_start` 直接开 WWDT0（LFCLK 32.768 kHz，窗口 0%，断点暂停时停） | 档位粗（2^6..2^25 拍 × 1..8 分频），取 ≥ 要求的最短档；500 ms 恰好一档。复位原因读 RSTCAUSE（读清，缓存）【编译】 |
| adc | — | 未实现（返回 DZ_ENOTSUP，有 adc 资源时编译报错） |
| i2c | I2C 实例 `I2C_<名>`，Controller，速率/上拉/滤波在 SysConfig | 轮询（参照 TI 例程 i2c_controller_rw_multibyte_fifo_poll）：写寄存器号不发 STOP + 重复起始读；写时边发边补 8 字节 FIFO；每步 5 ms 超时，出错/超时复位控制器状态机，计数进 `m0_diag()` |
| spi | 总线实例 `SPI_BUS<n>`（SPIn，MOTO3 三线，模式/速率在 SysConfig）+ 片选 GPIO 组 `GPIO_CS_SPI<n>_<名>`、引脚 `CS`（初值 SET） | 轮询逐字节收发配对，等 BUSY 清零再拉高片选；同一总线多个设备 = 多个片选组；n ≤ 64 |

时基：SysTick 1 ms（本层配置）。`main()` 在 `main_mspm0.c`（SysConfig 不生成 main）。

**验证状态**：【已实测】car_2wd、imu_module（MPU6050 走 I2C）交叉编译通过；`.syscfg` 由 SysConfig CLI 1.28 生成。I2C/SPI **【编译】未上板**：NACK、时钟拉伸、长度 > 8 的写都没在真芯片上测过。【未验证】全部上板行为；`boards/mspm0g3507-tianmengxing/syscfg/` 下的配置是合成样例。

## DAC（0.9.0，PAL 1.7.0）
- SysConfig 加 DAC12 模块（单例，G350x/G150x 只有 DAC0，输出 PA15）；board.yaml `dac:` 写 `instance: DAC0, channel: 0, pin: PA15, bits: 12`。`pal_dac_write` 直写 DATA0（`DL_DAC12_output12`）。validate_board 对 MSPM0G310x 等没有 DAC 的型号直接拒绝。【编译】未上板。

## ADC 与 GPIO 边沿中断（0.4.0，PAL 1.2.0）
- ADC：每个用到的 ADC12 外设在 SysConfig 里建一个实例，名字 `ADC12_<n>`（ADC0 → `ADC12_0`），单次、软件触发、MEM0；
  board.yaml `adc:` 写 `instance: ADC0, channel: <通道号>, pin: <引脚>`。`pal_adc_read` 每次把 MEM0 切到该通道，轮询结果（超时 1 ms，计入 `m0_diag()->adc_timeout`）。
- GPIO 中断：.syscfg 里引脚设成输入即可；`pal_gpio_irq_attach` 运行时设 RISE_FALL、开引脚中断和 GROUP1。
  板子有输入脚时 board_gen.c 生成 `GROUP1_IRQHandler`（编码器软件解码 + 边沿中断分发共用）。
- 【编译】两者都只交叉编译过，未上板。天猛星的 VBAT（PA25 / ADC0 CH2）和 US_TRIG/US_ECHO（PB8/PB9）是我挑的空闲脚，【未验证】未对照原理图。

## 掉电保存（0.7.0）

board.yaml `mcu.nvm_kb` > 0 时 `pal_nvm_*` 可用：Flash 末尾，扇区 1 KB，64 位 + 硬件 ECC 编程（DriverLib `*FromRAM`）。不改 SDK 链接脚本，另传 `nvm_guard.ld` 做越界 ASSERT；CCS：projectspec（gen_ccs_projectspec.py）带 `-DDZ_NVM_KB/-DDZ_FLASH_KB` 和 `boards/<板>/ccs/dz_nvm_linker.cmd`（tools/gen_ide_nvm.py 由 SDK ticlang 模板生成，FLASH 截掉末尾 nvm_kb、定义 `__dz_nvm_base`）；.syscfg 里 `ProjectConfig.genLinker = false`，不再用 SysConfig 生成的链接文件。tiarmclang 下运行时核对 `__dz_nvm_base`，没用这份 .cmd 链接直接报错。[编译]（make）/[未测]（CCS 里没编译过）
