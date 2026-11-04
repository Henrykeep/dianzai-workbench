/*
 * Vendored from LP-MSPM0G3507_freertos_firework@ede35a2 modules/dds/ad9833.h
 * MIT License, Copyright (c) 2026 阡陌 (full text: firmware/drivers/ad983x/LICENSE-firework.txt)
 * Local changes (XinTai): include paths point at ad983x_port.h (SPI/GPIO glue onto pal_*);
 * the APP_ENABLE_WAVEFORM_OUTPUT_* compile guard is removed (module is opt-in by linking).
 * Function bodies are the original code. The SPIWrite16 / SPIWriteAD9850Frame / BSPGPIO* calls they make
 * are NOT original: they resolve to XinTai glue in ad983x_port.c (AGPL-3.0-or-later), which maps them onto pal_*.
 */
/**
 * @file ad9833.h
 * @brief AD9833 硬件复位、频率、相位、波形和启停底层接口。
 */
#ifndef AD9833_H
#define AD9833_H

#include <stdbool.h>
#include <stdint.h>

#include "ad983x_port.h"


/** AD9833 是只写器件，驱动必须在软件中保存控制寄存器状态。 */
typedef struct {
    uint16_t control_shadow;
    DDSWaveform_e waveform;
    bool enabled;
    bool initialized;
} AD9833Context;

bool AD9833Initialize(AD9833Context *context, SPIInstance *spi,
    uint32_t reference_clock_hz, uint32_t frequency_hz,
    uint16_t phase_degrees, DDSWaveform_e waveform, bool enabled);

bool AD9833SetFrequency(AD9833Context *context, SPIInstance *spi,
    uint32_t reference_clock_hz, uint32_t frequency_hz);

bool AD9833SetPhase(AD9833Context *context, SPIInstance *spi,
    uint16_t phase_degrees);

bool AD9833SetWaveform(AD9833Context *context, SPIInstance *spi,
    DDSWaveform_e waveform);

bool AD9833SetEnabled(AD9833Context *context, SPIInstance *spi,
    bool enabled);

#endif
