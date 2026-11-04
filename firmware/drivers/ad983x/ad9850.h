/*
 * Vendored from LP-MSPM0G3507_freertos_firework@ede35a2 modules/dds/ad9850.h
 * MIT License, Copyright (c) 2026 阡陌 (full text: firmware/drivers/ad983x/LICENSE-firework.txt)
 * Local changes (XinTai): include paths point at ad983x_port.h (SPI/GPIO glue onto pal_*);
 * the APP_ENABLE_WAVEFORM_OUTPUT_* compile guard is removed (module is opt-in by linking).
 * Function bodies are the original code. The SPIWrite16 / SPIWriteAD9850Frame / BSPGPIO* calls they make
 * are NOT original: they resolve to XinTai glue in ad983x_port.c (AGPL-3.0-or-later), which maps them onto pal_*.
 */
/**
 * @file ad9850.h
 * @brief AD9850 复位、频率调谐字、相位/输出类型和启停底层接口。
 */
#ifndef AD9850_H
#define AD9850_H

#include <stdbool.h>
#include <stdint.h>


#include "ad983x_port.h"


/** AD9850 仅保存软件状态；器件串行接口不支持读回。 */
typedef struct {
    BSPGPIOInstance *reset_gpio;
    uint32_t reference_clock_hz;
    uint32_t frequency_hz;
    DDSWaveform_e waveform;
    bool enabled;
    bool initialized;
} AD9850Context;

bool AD9850Initialize(AD9850Context *context, SPIInstance *spi,
    uint32_t reference_clock_hz, uint32_t frequency_hz,
    DDSWaveform_e waveform, bool enabled);
bool AD9850SetFrequency(AD9850Context *context, SPIInstance *spi,
    uint32_t reference_clock_hz, uint32_t frequency_hz);
bool AD9850SetWaveform(AD9850Context *context, SPIInstance *spi,
    DDSWaveform_e waveform);
bool AD9850SetEnabled(AD9850Context *context, SPIInstance *spi,
    bool enabled);

#endif
