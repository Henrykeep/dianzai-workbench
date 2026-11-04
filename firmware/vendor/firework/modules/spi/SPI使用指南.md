# SPI Module 使用指南

`modules/spi` 在 BSP SPI 之上提供逻辑设备注册和 FreeRTOS 互斥保护。它不包含
DriverLib 类型，也不知道 PB6/PB8/PB9 等真实引脚。

## 基本用法

```c
SPIInstance *spi = SPIRegister(SPI_DEVICE_DDS_0);
uint16_t words[] = {0x2100U, 0x4000U};

if (spi != NULL) {
    (void)SPIWrite16(spi, words,
        sizeof(words) / sizeof(words[0]));
}
```

`SPIWrite16()` 使用静态 FreeRTOS mutex 保护整个数组，所以不同任务不会把一组
DDS 控制字交错。实例池和互斥锁均为静态分配，不使用堆内存。

当前逻辑设备 `SPI_DEVICE_DDS_0` 映射到 AD9833 的 SPI1 通道。以后共享同一条
SPI 总线时，应继续把一个不可拆分的寄存器序列放在同一次 `SPIWrite16()` 调用中。
该阻塞接口不应在 ISR 中调用。

AD9850 与 AD9833 共用 PB9 时钟和 PB8 数据线，但使用独立逻辑实例和专用事务：

```c
SPIInstance *ad9850_spi = SPIRegister(SPI_DEVICE_AD9850_0);
uint8_t frame[5] = {0U}; /* 4 字节调谐字 + 1 字节控制字。 */
(void)SPIWriteAD9850Frame(ad9850_spi, frame, sizeof(frame));
```

AD9833 和 AD9850 的两个实例共用同一把 SPI1 总线互斥锁。AD9850 事务会在锁内临时
切换为 Mode 0、8 位、LSB first，发送完后产生 FQ_UD 脉冲，并在返回前恢复 AD9833
所需的 Mode 2、16 位、MSB first；其他任务不能在格式切换中途插入数据。

TFT 使用独立的 SPI0 逻辑设备和 8 位写接口：

```c
SPIInstance *tft_spi = SPIRegister(SPI_DEVICE_TFT_0);
uint8_t command = 0x29U;
(void)SPIWrite8(tft_spi, &command, 1U);
```

`SPIWrite8()` 同样使用静态 mutex，一次调用对应一个完整的 TFT CS 窗口。

三个写接口都只接受与其匹配的逻辑设备：AD9833 使用 `SPIWrite16()`，TFT 使用
`SPIWrite8()`，AD9850 使用 `SPIWriteAD9850Frame()`；实例类型不匹配会返回 `false`。
