/*
 * Vendored from LP-MSPM0G3507_freertos_firework@ede35a2 modules/dds/ad9850.c
 * MIT License, Copyright (c) 2026 阡陌 (full text: firmware/drivers/ad983x/LICENSE-firework.txt)
 * Local changes (XinTai): include paths point at ad983x_port.h (SPI/GPIO glue onto pal_*);
 * the APP_ENABLE_WAVEFORM_OUTPUT_* compile guard is removed (module is opt-in by linking). Logic unchanged.
 */
/* AD9850 驱动生成 40 位串行配置帧，并管理 RESET 与 FQ_UD 更新时序。 */
#include "ad9850.h"



#include <stddef.h>

#define AD9850_TUNING_MODULUS (4294967296ULL)

static bool AD9850BuildFrame(uint32_t reference_clock_hz,
    uint32_t frequency_hz, uint8_t frame[5]);
static bool AD9850IsWaveformSupported(DDSWaveform_e waveform);
static bool AD9850ContextIsValid(const AD9850Context *context,
    const SPIInstance *spi);

/* 复位后用一次完整 40 位帧装载频率字；FQ_UD 由 SPI 层在帧末尾产生。 */
bool AD9850Initialize(AD9850Context *context, SPIInstance *spi,
    uint32_t reference_clock_hz, uint32_t frequency_hz,
    DDSWaveform_e waveform, bool enabled)
{
    uint8_t frame[5];
    BSPGPIOInstance *reset_gpio;

    if ((context == NULL) || (spi == NULL) ||
        !AD9850IsWaveformSupported(waveform) ||
        !AD9850BuildFrame(reference_clock_hz, frequency_hz, frame)) {
        return false;
    }

    reset_gpio = BSPGPIORegister(BSP_GPIO_CHANNEL_AD9850_RESET);
    if ((reset_gpio == NULL) || !BSPGPIOWrite(reset_gpio, true) ||
        !BSPGPIOWrite(reset_gpio, false)) {
        return false;
    }

    /* 复位序列后的第一拍用于进入串行模式（对应参考程序的 W_CLK 脉冲）。 */
    frame[0] = 0U;
    if (!SPIWriteAD9850Frame(spi, frame, 1U) ||
        !SPIWriteAD9850Frame(spi, frame, sizeof(frame))) {
        return false;
    }

    context->reset_gpio = reset_gpio;
    context->reference_clock_hz = reference_clock_hz;
    context->frequency_hz = frequency_hz;
    context->waveform = waveform;
    context->enabled = true;
    context->initialized = true;
    if (!enabled) {
        return AD9850SetEnabled(context, spi, false);
    }
    return true;
}

/* 以 round(fout * 2^32 / fref) 生成低字节在前的 32 位调谐字。 */
bool AD9850SetFrequency(AD9850Context *context, SPIInstance *spi,
    uint32_t reference_clock_hz, uint32_t frequency_hz)
{
    uint8_t frame[5];

    if (!AD9850ContextIsValid(context, spi) ||
        !AD9850BuildFrame(reference_clock_hz, frequency_hz, frame) ||
        !SPIWriteAD9850Frame(spi, frame, sizeof(frame))) {
        return false;
    }
    context->reference_clock_hz = reference_clock_hz;
    context->frequency_hz = frequency_hz;
    return true;
}

/* AD9850 的 SIN/SQ 引脚由硬件选择；此项保存当前菜单所选输出端。 */
bool AD9850SetWaveform(AD9850Context *context, SPIInstance *spi,
    DDSWaveform_e waveform)
{
    if (!AD9850ContextIsValid(context, spi) ||
        !AD9850IsWaveformSupported(waveform)) {
        return false;
    }
    context->waveform = waveform;
    return true;
}

/* RESET 高电平停止模块；重新启动时释放复位，当前频率由此前锁存字恢复。 */
bool AD9850SetEnabled(AD9850Context *context, SPIInstance *spi,
    bool enabled)
{
    uint8_t frame[5];

    if (!AD9850ContextIsValid(context, spi) ||
        !BSPGPIOWrite(context->reset_gpio, !enabled)) {
        return false;
    }
    if (enabled &&
        (!AD9850BuildFrame(context->reference_clock_hz,
             context->frequency_hz, frame) ||
         !SPIWriteAD9850Frame(spi, frame, sizeof(frame)))) {
        (void)BSPGPIOWrite(context->reset_gpio, true);
        return false;
    }
    context->enabled = enabled;
    return true;
}

static bool AD9850BuildFrame(uint32_t reference_clock_hz,
    uint32_t frequency_hz, uint8_t frame[5])
{
    uint64_t scaled_frequency;
    uint32_t tuning_word;

    if ((reference_clock_hz == 0U) || (frequency_hz == 0U) ||
        (frequency_hz > (reference_clock_hz / 2U)) || (frame == NULL)) {
        return false;
    }
    scaled_frequency = ((uint64_t)frequency_hz * AD9850_TUNING_MODULUS) +
                       (reference_clock_hz / 2U);
    tuning_word = (uint32_t)(scaled_frequency / reference_clock_hz);
    frame[0] = (uint8_t)(tuning_word & 0xFFU);
    frame[1] = (uint8_t)((tuning_word >> 8U) & 0xFFU);
    frame[2] = (uint8_t)((tuning_word >> 16U) & 0xFFU);
    frame[3] = (uint8_t)((tuning_word >> 24U) & 0xFFU);
    frame[4] = 0U;
    return true;
}

static bool AD9850IsWaveformSupported(DDSWaveform_e waveform)
{
    return (waveform == DDS_WAVEFORM_SINE) ||
           (waveform == DDS_WAVEFORM_SQUARE);
}

static bool AD9850ContextIsValid(const AD9850Context *context,
    const SPIInstance *spi)
{
    return (context != NULL) && context->initialized &&
           (context->reset_gpio != NULL) && (spi != NULL);
}

