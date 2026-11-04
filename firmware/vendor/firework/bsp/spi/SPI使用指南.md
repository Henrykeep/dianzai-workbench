# BSP SPI 使用指南

`bsp/spi` 封装 MSPM0G3507 的 SPI1/SPI0，以及 AD9833、AD9850、TFT 的手动控制线，只有本层
包含 `ti_msp_dl_config.h`。上层只使用逻辑通道，不直接依赖真实端口宏。

## 硬件配置

| 信号 | MCU 引脚 | SysConfig 配置 |
| --- | --- | --- |
| AD9833 SCLK | PB9 | SPI1，1 MHz，16 位，Mode 2 |
| AD9833 SDATA | PB8 | SPI1 PICO，只发送 |
| AD9833 FSYNC | PB6 | 普通 GPIO，初始高电平 |
| AD9850 W_CLK / DATA | PB9 / PB8 | 与 AD9833 共用 SPI1 引脚，事务时切换为 Mode 0、8 位、LSB First |
| AD9850 FQ_UD / RESET | PB5 / PA1 | 锁存脉冲 / 硬件复位 |
| TFT SCLK | PB18 | SPI0，8 MHz，8 位，Mode 0 |
| TFT MOSI | PB17 | SPI0 PICO，只发送 |
| TFT CS | PB20 | 普通 GPIO，初始高电平 |

SPI1 使用 1 MHz、16 位、MSB First、Motorola 3-wire、CPOL=1、CPHA=0。PB7
没有分配给 SPI，AD9833 也不需要 MISO/POCI。

## 公共接口

```c
BSPSPIInstance *BSPSPIRegister(BSP_SPI_Channel_e channel);

bool BSPSPIWrite16(BSPSPIInstance *instance,
    const uint16_t *words, size_t word_count);

bool BSPSPIWrite8(BSPSPIInstance *instance,
    const uint8_t *bytes, size_t byte_count);

bool BSPSPIWriteAD9850Frame(BSPSPIInstance *instance,
    const uint8_t *bytes, size_t byte_count);
```

`BSPSPIWrite16()` 的一次调用对应一个完整事务：等待 SPI 空闲，将 FSYNC 拉低，
连续发送所有 16 位字，等待最后一个字移出后再将 FSYNC 拉高。所有错误出口也会
恢复 FSYNC 高电平。轮询带超时，不使用 DMA 和中断。

DDS 是只写设备，SPI 同步产生的接收 FIFO 数据会被及时清空。该接口只能证明
MSPM0 SPI 传输已经完成，不能检测外部 AD9833 是否接线正确或已经上电。

`BSPSPIWrite8()` 只用于 TFT 通道，每次调用在一个 CS 低电平窗口中发送
一组命令或像素字节。TFT 的 DC 和 RESET 由 BSP GPIO 通道管理。

`BSPSPIWriteAD9850Frame()` 临时把共用 SPI1 切换为 AD9850 所需的 Mode 0、8 位、
LSB First，发送完整帧后产生 FQ_UD 脉冲，并在所有返回路径恢复 AD9833 的
Mode 2、16 位、MSB First 配置。AD9833 和 AD9850 共用 PB9/PB8，通常只安装并启用
当前实际连接的一种模块；同时连接时仍需实板验证总线和上电状态不会互相驱动。

## 使用限制

- 这是阻塞接口，应从任务或启动初始化上下文调用，不要从 ISR 调用。
- 修改引脚或 SPI 模式时，先修改 `blink_led.syscfg`，再核对本层逻辑映射。
- SPI SCLK 只负责写寄存器，不是 AD9833 的 MCLK 参考时钟。
