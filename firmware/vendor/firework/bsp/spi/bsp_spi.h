/**
 * @file bsp_spi.h
 * @brief DDS、AD9850 与 TFT 设备专用 SPI 发送事务接口。
 */
#ifndef BSP_SPI_H
#define BSP_SPI_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** LP-MSPM0G3507 板级层向上提供的逻辑 SPI 通道。 */
typedef enum {
    /* AD9833 控制总线：PB9(SCLK)、PB8(SDATA)、PB6(FSYNC)。 */
    BSP_SPI_CHANNEL_DDS_0 = 0,
    /* AD9850 控制总线：与 AD9833 共用 PB9(SCLK)、PB8(SDATA)，FQ_UD=PB5。 */
    BSP_SPI_CHANNEL_AD9850_0,
    /* ST7735S TFT 总线：PB18(SCLK)、PB17(SDATA)、PB20(CS)。 */
    BSP_SPI_CHANNEL_TFT_0,
    /* 通道总数，同时作为枚举范围上限。 */
    BSP_SPI_CHANNEL_COUNT
} BSP_SPI_Channel_e;

/** SPI 不透明实例，真实寄存器和片选 GPIO 仅保留在 BSP 内部。 */
typedef struct BSPSPIInstance BSPSPIInstance;

/** 注册指定板级 SPI 通道；参数非法时返回 NULL。 */
BSPSPIInstance *BSPSPIRegister(BSP_SPI_Channel_e channel);

/**
 * @brief 在一次 FSYNC 有效窗口内阻塞发送若干个 16 位字。
 *
 * @return 发送完成返回 true；参数非法或等待硬件超时返回 false。
 */
bool BSPSPIWrite16(BSPSPIInstance *instance,
    const uint16_t *words, size_t word_count);

/** 在一次 CS 有效窗口内阻塞发送若干个 8 位字节。 */
bool BSPSPIWrite8(BSPSPIInstance *instance,
    const uint8_t *bytes, size_t byte_count);

/**
 * @brief 以 AD9850 串行格式发送一帧，并在最后一个时钟后产生 FQ_UD 锁存脉冲。
 *
 * 该函数临时把共用 SPI1 切换为 Mode 0、8 位、LSB first；返回前始终恢复
 * AD9833 所需的 Mode 2、16 位、MSB first。
 */
bool BSPSPIWriteAD9850Frame(BSPSPIInstance *instance,
    const uint8_t *bytes, size_t byte_count);

#endif
