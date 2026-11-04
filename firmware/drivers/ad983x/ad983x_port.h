/**
 * @file ad983x_port.h
 * @brief AD9833 / AD9850 外置 DDS 芯片驱动的移植层：把原项目的 SPIInstance / BSPGPIO 接口接到 pal_*。
 *
 * ad9833.c / ad9850.c 原样取自 LP-MSPM0G3507_freertos_firework@ede35a2 modules/dds（MIT，阡陌），
 * 这里只提供它们调用的 SPIWrite16 / SPIWriteAD9850Frame / BSPGPIORegister / BSPGPIOWrite 和 DDSWaveform_e。
 * 原 modules/spi/spi.c 是 FreeRTOS 互斥量 + MSPM0 DriverLib 寄存器操作，不可移植，未搬；
 * 本层不加锁——同一条 SPI 总线上的多个设备请在同一个任务里调用。
 *
 * 接线（board.yaml）：
 *   AD9833：spi 一条，mode: 2（CPOL=1 CPHA=0），cs 接 FSYNC，≤ 40 MHz。
 *   AD9850：spi 一条，mode: 0，sck 接 W_CLK，mosi 接 D7（串行模式要求 D0=D1=VCC、D2=GND），cs 可接空脚；
 *           gpio 两条输出：FQ_UD、RESET（高有效）。
 * 版本：AD983X_VERSION
 */
#ifndef AD983X_PORT_H
#define AD983X_PORT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "dz_err.h"
#include "pal.h"

#define AD983X_VERSION "1.0.0"

/** 原 modules/dds/dds.h 的波形枚举（值不变）。AD9850 只有 SINE / SQUARE（方波来自比较器引脚）。 */
typedef enum {
    DDS_WAVEFORM_SINE = 0,
    DDS_WAVEFORM_TRIANGLE,
    DDS_WAVEFORM_SQUARE,
    DDS_WAVEFORM_COUNT
} DDSWaveform_e;

/** 一个 SPI 逻辑设备。用 ad983x_spi_ad9833 / ad983x_spi_ad9850 填写。 */
typedef struct SPIInstance {
    pal_id_t spi;
    pal_id_t fq_ud;          /**< AD9850 才用；AD9833 为 PAL_ID_NONE */
    bool     lsb_first;      /**< AD9850 串行帧低位在前（pal_spi 是 MSB 先出，本层逐字节翻转） */
    uint32_t frames;         /**< 已发出的帧数（诊断用） */
} SPIInstance;

/** 原 bsp_gpio 的输出脚。 */
typedef struct BSPGPIOInstance { pal_id_t id; } BSPGPIOInstance;

/** 原项目固定的 GPIO 通道号；本层只用到 AD9850 的 RESET。 */
typedef enum { BSP_GPIO_CHANNEL_AD9850_RESET = 0, BSP_GPIO_CHANNEL_COUNT } BSP_GPIO_Channel_e;

void ad983x_spi_ad9833(SPIInstance *s, pal_id_t spi);
void ad983x_spi_ad9850(SPIInstance *s, pal_id_t spi, pal_id_t fq_ud);
/** AD9850Initialize 之前调用：绑定 RESET 脚（原项目由 BSPGPIORegister 固定通道取得）。 */
void ad983x_bind_ad9850_reset(pal_id_t reset);

/* —— 被 ad9833.c / ad9850.c 调用的原接口 —— */
bool SPIWrite16(SPIInstance *instance, const uint16_t *words, size_t word_count);
bool SPIWriteAD9850Frame(SPIInstance *instance, const uint8_t *bytes, size_t byte_count);
BSPGPIOInstance *BSPGPIORegister(BSP_GPIO_Channel_e channel);
bool BSPGPIOWrite(BSPGPIOInstance *instance, bool active);

/* —— 频率字（与驱动内部同公式，单测与上层显示“实际频率”用） —— */
/** AD9833：round(f·2^28/fref)，28 位。参数非法（fref=0、>25 MHz、f=0、f>fref/2）返回 0。 */
uint32_t ad9833_ftw(uint32_t fref_hz, uint32_t f_hz);
/** AD9850：round(f·2^32/fref)，32 位。参数非法返回 0。 */
uint32_t ad9850_ftw(uint32_t fref_hz, uint32_t f_hz);
/** 频率字对应的实际输出（毫赫兹）：ftw·fref/2^bits。 */
uint64_t ad983x_actual_mhz(uint32_t ftw, uint32_t fref_hz, unsigned bits);

#endif /* AD983X_PORT_H */
