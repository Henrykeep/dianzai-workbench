/**
 * @file spi.h
 * @brief DDS、AD9850 与 TFT 逻辑设备的线程安全 SPI 写入接口。
 */
#ifndef SPI_H
#define SPI_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** 应用层可使用的逻辑 SPI 设备总线。 */
typedef enum {
    /* 连接外部 DDS 的 SPI1 总线。 */
    SPI_DEVICE_DDS_0 = 0,
    /* AD9850，与 AD9833 共用同一条 SPI1 物理总线。 */
    SPI_DEVICE_AD9850_0,
    /* 连接 ST7735S TFT 的 SPI0 总线。 */
    SPI_DEVICE_TFT_0,
    /* 逻辑 SPI 设备总数，同时作为枚举范围上限。 */
    SPI_DEVICE_COUNT
} SPI_Device_e;

/** SPI 模块的不透明实例。 */
typedef struct SPIInstance SPIInstance;

/** 注册指定逻辑 SPI 设备；失败时返回 NULL。 */
SPIInstance *SPIRegister(SPI_Device_e device);

/** 线程安全地在一个片选窗口内发送若干个 16 位字。 */
bool SPIWrite16(SPIInstance *instance,
    const uint16_t *words, size_t word_count);

/** 线程安全地在一个片选窗口内发送若干个 8 位字节。 */
bool SPIWrite8(SPIInstance *instance,
    const uint8_t *bytes, size_t byte_count);

/** 线程安全地写入 AD9850 的 LSB-first 串行帧并锁存 FQ_UD。 */
bool SPIWriteAD9850Frame(SPIInstance *instance,
    const uint8_t *bytes, size_t byte_count);

#endif
