/**
 * @file ad9850.h
 * @brief AD9850 复位、频率调谐字、相位/输出类型和启停底层接口。
 */
#ifndef AD9850_H
#define AD9850_H

#include <stdbool.h>
#include <stdint.h>

#include "bsp/gpio/bsp_gpio.h"
#include "modules/dds/dds.h"
#include "modules/spi/spi.h"

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
