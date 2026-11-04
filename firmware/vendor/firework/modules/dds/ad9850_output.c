/*
 * AD9850 默认输出服务把项目级启停、频率和波形接口适配到通用 DDS Module。
 */
#include "modules/dds/ad9850_output.h"

#include "application/app_config.h"

#if APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U

#include <stddef.h>

#include "modules/dds/dds.h"

#define AD9850_OUTPUT_DEFAULT_FREQUENCY_HZ (1000UL)

/* 当前产品只暴露一个 AD9850 默认输出实例。 */
static DDSInstance *ad9850_output;

static bool AD9850OutputConvertWaveform(AD9850OutputWaveform_e source,
    DDSWaveform_e *destination);

bool AD9850OutputInit(uint32_t reference_clock_hz)
{
    DDSConfig config;

    if (ad9850_output != NULL) {
        return true;
    }
    /* 初始化只建立配置和复位硬件，默认保持输出关闭。 */
    config.chip = DDS_CHIP_AD9850;
    config.reference_clock_hz = reference_clock_hz;
    config.initial_frequency_hz = AD9850_OUTPUT_DEFAULT_FREQUENCY_HZ;
    config.initial_phase_degrees = 0U;
    config.initial_waveform = DDS_WAVEFORM_SINE;
    config.start_enabled = false;
    ad9850_output = DDSRegister(DDS_DEVICE_OUTPUT_1, &config);
    return ad9850_output != NULL;
}

bool AD9850OutputSetFrequency(uint32_t frequency_hz)
{
    return (ad9850_output != NULL) &&
           DDSSetFrequency(ad9850_output, frequency_hz);
}

bool AD9850OutputSetWaveform(AD9850OutputWaveform_e waveform)
{
    DDSWaveform_e dds_waveform;

    return (ad9850_output != NULL) &&
           AD9850OutputConvertWaveform(waveform, &dds_waveform) &&
           DDSSetWaveform(ad9850_output, dds_waveform);
}

bool AD9850OutputStart(void)
{
    return (ad9850_output != NULL) && DDSStart(ad9850_output);
}

bool AD9850OutputStop(void)
{
    return (ad9850_output != NULL) && DDSStop(ad9850_output);
}

bool AD9850OutputGetState(AD9850OutputState *state)
{
    DDSState dds_state;

    if ((state == NULL) || (ad9850_output == NULL) ||
        !DDSGetState(ad9850_output, &dds_state)) {
        return false;
    }
    /* 对外状态只保留 AD9850 硬件实际支持的正弦和方波。 */
    state->frequency_hz = dds_state.frequency_hz;
    state->enabled = dds_state.enabled;
    if (dds_state.waveform == DDS_WAVEFORM_SINE) {
        state->waveform = AD9850_OUTPUT_WAVEFORM_SINE;
    } else if (dds_state.waveform == DDS_WAVEFORM_SQUARE) {
        state->waveform = AD9850_OUTPUT_WAVEFORM_SQUARE;
    } else {
        return false;
    }
    return true;
}

static bool AD9850OutputConvertWaveform(AD9850OutputWaveform_e source,
    DDSWaveform_e *destination)
{
    if (destination == NULL) {
        return false;
    }
    /* 显式映射枚举，避免两个公开枚举以后扩展时依赖数值恰好相同。 */
    switch (source) {
        case AD9850_OUTPUT_WAVEFORM_SINE:
            *destination = DDS_WAVEFORM_SINE;
            return true;
        case AD9850_OUTPUT_WAVEFORM_SQUARE:
            *destination = DDS_WAVEFORM_SQUARE;
            return true;
        default:
            return false;
    }
}

#endif /* APP_ENABLE_WAVEFORM_OUTPUT_AD9850 */
