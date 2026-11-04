# ad983x — AD9833 / AD9850 外置 DDS 信号源芯片  `v1.0.0`

**驱动代码原样搬自** LP-MSPM0G3507_freertos_firework@ede35a2 `modules/dds/ad9833.c|h`、`ad9850.c|h`（MIT，Copyright (c) 2026 阡陌，许可原文 `LICENSE-firework.txt`）。
只改了 include 路径、去掉原工程的 `APP_ENABLE_*` 编译开关；寄存器时序、频率字取整、控制字影子全部是原代码。
它们调用的 `SPIWrite16` / `SPIWriteAD9850Frame` / `BSPGPIO*` 不是原代码，而是芯台胶水（`ad983x_port.c`，AGPL-3.0-or-later）。
`ad983x_port.c` 是本仓库写的薄移植层：原项目的 `SPIWrite16` / `SPIWriteAD9850Frame` / `BSPGPIO*` → `pal_spi_xfer` / `pal_gpio_write`，所以所有 pal 板（STM32F1/F4、MSPM0G3507、host-sim）都能编。

| 芯片 | 频率字 | 分辨率（典型时钟） | 波形 |
|---|---|---|---|
| AD9833 | round(f·2²⁸/fMCLK)，28 位，fMCLK ≤ 25 MHz | 25 MHz → 0.093 Hz | 正弦 / 三角 / 方波（MSB/2） |
| AD9850 | round(f·2³²/CLKIN)，32 位 | 125 MHz → 0.029 Hz | 正弦 + 比较器方波 |

## board.yaml
```yaml
spi:
  - { name: DDS,    instance: SPI1, sck: PA5, mosi: PA7, miso: PA6, cs: PA4, mode: 2, hz: 8000000 }   # AD9833：cs=FSYNC
  - { name: AD9850, instance: SPI1, sck: PA5, mosi: PA7, miso: PA6, cs: PB9, mode: 0, hz: 8000000 }   # cs 接空脚；mosi→D7
gpio:
  - { name: AD9850_FQUD, pin: PB10, dir: out }
  - { name: AD9850_RST,  pin: PB11, dir: out }
```
AD9850 模块要接成串行模式：D0、D1 接 VCC，D2 接 GND（多数蓝色小板默认如此）。

## 用法
```c
SPIInstance spi; AD9833Context dds = {0};
ad983x_spi_ad9833(&spi, RES_SPI_DDS);
AD9833Initialize(&dds, &spi, 25000000u, 1000u, 0u, DDS_WAVEFORM_SINE, true);
AD9833SetFrequency(&dds, &spi, 25000000u, 12345u);

SPIInstance s2; AD9850Context a = {0};
ad983x_spi_ad9850(&s2, RES_SPI_AD9850, RES_GPIO_AD9850_FQUD);
ad983x_bind_ad9850_reset(RES_GPIO_AD9850_RST);
AD9850Initialize(&a, &s2, 125000000u, 1000000u, DDS_WAVEFORM_SINE, true);
```
频率是整数 Hz（原接口）；`ad9833_ftw()` / `ad9850_ftw()` / `ad983x_actual_mhz()` 给上层显示实际频率。
本层不加锁：同一 SPI 总线上的设备请在同一任务里调用（原工程的 FreeRTOS 互斥量没搬）。

## 和 algo/dds 的关系
algo/dds 是**片内 DAC 软件 DDS**（定时器 + DMA，≤ 几十 kHz），本驱动是**外置 DDS 芯片**（AD9833 到 12.5 MHz、AD9850 到 ~40 MHz）。两者不互相替代，都保留。

## 验证状态
- **已实测（PC 主机，tests/host/test_signal.c）**：假芯片按 SPI 字节解码——AD9833 初始化 8 字序列（RESET→FREQ0/1→PHASE0/1→控制字）、28 位频率字与数据手册例子（fMCLK 25 MHz、400 Hz → 0x10C7）一致、相位字、三角/方波/关断控制位；AD9850 40 位帧 LSB 先出、FQ_UD 锁存、RESET 脚、数据手册例子（CLKIN 125 MHz、1 MHz → 0x020C49BA）。
- **交叉编译**：`make cross` 所有 STM32 / MSPM0 组合都链接本目录。
- **【未测】上板**：没有实物模块，SPI 模式与 FSYNC 时序按数据手册写，第一次上板请用示波器看 SCLK/FSYNC。
