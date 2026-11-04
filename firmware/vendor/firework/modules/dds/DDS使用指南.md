# DDS Module 使用指南

`modules/dds` 提供 AD9833/AD9850 共用的 DDS 注册、配置、启停和状态接口，
两种芯片的帧编码分别放在 `ad9833.c/.h` 和 `ad9850.c/.h` 后端。Application
不需要直接拼接控制字或 40 位串行帧。

同目录中有两组项目级便捷接口：

- `dds_output.c/.h`：默认 AD9833 实例；
- `ad9850_output.c/.h`：默认 AD9850 实例。

两者都由 `application/waveform/waveform_output` 对业务层暴露。当前
`application/app_config.h` 默认开启 DAC 后端，AD9833 和 AD9850 两个开关均为
`0U`；使用外部 DDS 模块前必须显式开启对应开关。

## 通用 DDS 设备映射

`DDSRegister()` 先按逻辑设备选择 SPI 通道，再按 `DDSConfig.chip` 选择芯片
后端。当前必须使用下列成对组合；混用设备号和芯片类型会因 SPI 事务
类型不匹配而注册失败。

| 逻辑设备 | 芯片后端 | SPI 逻辑设备 | 独立控制线 |
| --- | --- | --- | --- |
| `DDS_DEVICE_OUTPUT_0` | `DDS_CHIP_AD9833` | `SPI_DEVICE_DDS_0` | PB6 / FSYNC |
| `DDS_DEVICE_OUTPUT_1` | `DDS_CHIP_AD9850` | `SPI_DEVICE_AD9850_0` | PB5 / FQ_UD，PA1 / RESET |

AD9833 和 AD9850 共用 SPI1 的 PB9(SCLK) 和 PB8(SDATA)，但有各自的锁存、
片选或复位线。底层使用共享总线锁防止事务交错，并在 AD9850 事务后恢复
AD9833 所需的 SPI 格式。产品配置注释目前按“一次只装一种模块”给出建议；
若实际同时安装两块模块，除分别开启两个后端外，还需在实板确认共地、
电平和两路锁存时序。

## AD9833 接线

当前工程在 `blink_led.syscfg` 中使用 SPI1 控制 AD9833，接线如下：

| MSPM0G3507 开发板 | AD9833 模块 | 用途 |
| --- | --- | --- |
| PB9 | SCLK/CLK | SPI 串行时钟 |
| PB8 | SDATA/DATA | SPI 数据，MCU 输出到 AD9833 |
| PB6 | FSYNC/CS | 帧同步/片选 |
| 3.3V | VCC | 模块电源，优先使用 3.3 V |
| GND | GND | 电源地和信号参考地 |
| 不连接 MCU | VOUT | AD9833 波形输出，接示波器探头或后级电路 |

测量输出时：

```text
示波器探头尖端 -> AD9833 VOUT
示波器地夹     -> AD9833 GND
开发板 GND     -> AD9833 GND
```

开发板、AD9833 和示波器必须共地。不要把 VOUT 接到 PB8；PB8 只是写寄存器的
数字控制线，不是波形输出。

常见 AD9833 模块板载 25 MHz 晶振，不需要连接 MCU 的 MCLK。若使用的是不带
晶振的 AD9833 裸芯片或精简板，还必须给 MCLK 引脚提供稳定参考时钟，并把
`BSP_BOARD_DDS_REFERENCE_CLOCK_HZ` 改成实际时钟频率。

AD9833 的 VOUT 是带直流偏置的小幅模拟信号，不是 0～3.3 V 逻辑输出。直接接
示波器高阻输入即可观察；需要更大幅度、驱动负载或调整偏置时，应增加运放缓冲、
放大和滤波电路。

> 不同模块丝印可能写成 `CLK/DATA/FNC`、`SCLK/SDATA/FSYNC` 或
> `SCK/MOSI/CS`，应按信号功能对应，不要只按插针排列顺序接线。

## AD9833 注册和控制

```c
static const DDSConfig config = {
    DDS_CHIP_AD9833,
    25000000UL,
    1000UL,
    0U,
    DDS_WAVEFORM_SINE,
    true
};

DDSInstance *dds = DDSRegister(DDS_DEVICE_OUTPUT_0, &config);

(void)DDSSetFrequency(dds, 10000UL);
(void)DDSSetPhase(dds, 90U);
(void)DDSSetWaveform(dds, DDS_WAVEFORM_TRIANGLE);
(void)DDSStop(dds);
(void)DDSStart(dds);
```

工程内的 `DDSOutputInit()` 默认使用 `start_enabled=false`：初始化时写入
1 kHz、0° 正弦波参数，但保持 RESET/SLEEP，调用 `DDSOutputStart()` 或从菜单
选择 `OUTPUT ON` 后才开始输出。

AD9833 的 MCLK 配置必须非零且不超过 25 MHz，频率范围为 `1 Hz～MCLK/2`，
相位范围为 `0～359°`。`DDSGetState()` 返回最近一次
成功发送到芯片的频率、相位、波形和启停状态快照。

## AD9850 注册和限制

```c
static const DDSConfig ad9850_config = {
    DDS_CHIP_AD9850,
    125000000UL,
    1000000UL,
    0U,
    DDS_WAVEFORM_SINE,
    false
};

DDSInstance *ad9850 =
    DDSRegister(DDS_DEVICE_OUTPUT_1, &ad9850_config);
```

AD9850 的参考时钟和输出频率必须非零，输出频率不得超过参考时钟的一半。
注册时初始相位必须是 `0U`，初始波形只能为正弦或方波；
`DDSSetPhase()` 对 AD9850 始终返回 `false`，设置三角波也会失败。AD9850 模块的
SIN 和 SQ 是两个物理输出端，`DDSSetWaveform()` 只保存业务层当前选择，
不能在芯片内部切换外部接线。更完整的接线、调谐字和菜单说明见
[AD9850 模块使用指南](AD9850使用指南.md)。

## AD9833 编码

频率调谐字使用 64 位四舍五入计算：

```text
tuning_word = round(frequency_hz × 2^28 / reference_clock_hz)
```

28 位结果拆成两个 14 位字，先发送低 14 位，再发送高 14 位。相位换算为 4096
个步进：

```text
phase_word = round(phase_degrees × 4096 / 360)
```

25 MHz MCLK、400 Hz 的官方校验向量中，FREQ0 两个字为 `0x50C7, 0x4000`，
与本驱动的低位在前顺序一致。

波形控制关系：

| 波形 | AD9833 控制 |
| --- | --- |
| 正弦波 | DAC 输出，MODE=0 |
| 三角波 | DAC 输出，MODE=1 |
| 方波 | OPBITEN=1、DIV2=1，并关闭内部 DAC |

初始化先发送 `B28 + RESET`，再初始化 FREQ0/FREQ1 和 PHASE0/PHASE1，最后按
配置启动或保持休眠。`DDSStop()` 会设置 RESET、SLEEP1 和 SLEEP12，但 VOUT
不保证变为高阻。

## 线程安全和只写限制

DDS 层使用静态 mutex 保护后端状态和通用快照，锁顺序固定为
`DDS mutex → SPI mutex`。没有动态实例分配，这些阻塞接口不应从 ISR 调用。
AD9833 和 AD9850 都没有当前实现可使用的读回或应答信号，因此软件保存最近
一次成功发送的逻辑状态；“写入成功”只表示 MCU 侧 GPIO/SPI 事务完成，
不能证明器件已正确接线或实际输出正确。

参考资料：

- [AD9833 产品页](https://www.analog.com/en/products/ad9833.html)
- [AD9833 Rev.G 数据手册](https://www.analog.com/media/en/technical-documentation/data-sheets/AD9833.pdf)
- [AN-1070 编程应用笔记](https://www.analog.com/en/resources/app-notes/an-1070.html)
