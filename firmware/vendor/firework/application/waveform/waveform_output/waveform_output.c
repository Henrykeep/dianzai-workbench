/*
 * 波形输出层统一管理 DAC、DDS 和 AD9850 的生命周期与安全状态。
 * 上层只设置抽象波形参数，本文件负责检查范围、转换类型并调用具体驱动。
 */
#include "application/waveform/waveform_output/waveform_output.h"

#include <stddef.h>

#include "application/app_config.h"
#include "application/communication/serial_communication/serial_communication.h"
#include "application/task/task_manager.h"
#include "modules/dac/dac_output.h"
#include "modules/dds/dds_output.h"
#include "modules/dds/ad9850_output.h"

/* 本开关只控制本 Application 的低频 UART0 状态信息。 */
#define WAVEFORM_OUTPUT_DEBUG_OUTPUT_ENABLED (1U)

#if APP_ENABLE_WAVEFORM_OUTPUT != 0U
/* initializing 标志防止初始化链重入，initialized 表示所有已选后端均已就绪。 */
static bool waveform_output_initialized;
static bool waveform_output_initializing;

static void WaveformOutputDebugSend(
    const uint8_t *data, size_t size);
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
static bool WaveformOutputConvertDACConfig(
    const WaveformOutputDACConfig *source,
    DACOutputWaveformConfig *destination);
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U
static bool WaveformOutputConvertDDSWaveform(
    WaveformOutputDDSWaveform_e source,
    DDSOutputWaveform_e *destination);
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U
static bool WaveformOutputConvertAD9850Waveform(
    WaveformOutputAD9850Waveform_e source,
    AD9850OutputWaveform_e *destination);
#endif

bool WaveformOutputInit(void)
{
#if APP_ENABLE_WAVEFORM_OUTPUT == 0U
    return false;
#else
    static const uint8_t init_message[] =
        "WAVEFORM OUTPUT INIT\r\n";
#if (APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U) || \
    (APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U) || \
    (APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U)
    static const uint8_t error_message[] =
        "WAVEFORM OUTPUT ERROR\r\n";
#endif
#if (APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U)
    static const uint8_t ready_message[] =
        "WAVEFORM OUTPUT READY DAC DDS\r\n";
#elif APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    static const uint8_t ready_message[] =
        "WAVEFORM OUTPUT READY DAC\r\n";
#elif APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U
    static const uint8_t ready_message[] =
        "WAVEFORM OUTPUT READY DDS\r\n";
#elif APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U
    static const uint8_t ready_message[] =
        "WAVEFORM OUTPUT READY AD9850\r\n";
#endif

    if (waveform_output_initialized) {
        return true;
    }
    if (waveform_output_initializing) {
        return false;
    }
    waveform_output_initializing = true;

    WaveformOutputDebugSend(
        init_message, sizeof(init_message) - 1U);
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    {
        TaskHandle_t refill_task_handle;

        if (!DACOutputInit()) {
            WaveformOutputDebugSend(
                error_message, sizeof(error_message) - 1U);
            waveform_output_initializing = false;
            return false;
        }
        refill_task_handle = ApplicationTaskCreate(
            APPLICATION_TASK_DAC_REFILL, DACOutputRefillTask, NULL);
        if ((refill_task_handle == NULL) ||
            !DACOutputSetRefillTaskHandle(refill_task_handle)) {
            (void)DACOutputStop();
            WaveformOutputDebugSend(
                error_message, sizeof(error_message) - 1U);
            waveform_output_initializing = false;
            return false;
        }
    }
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U
    if (!DDSOutputInit()) {
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
        (void)DACOutputStop();
#endif
        WaveformOutputDebugSend(
            error_message, sizeof(error_message) - 1U);
        waveform_output_initializing = false;
        return false;
    }
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U
    if (!AD9850OutputInit(APP_AD9850_REFERENCE_CLOCK_HZ)) {
#if APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U
        (void)DDSOutputStop();
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
        (void)DACOutputStop();
#endif
        WaveformOutputDebugSend(
            error_message, sizeof(error_message) - 1U);
        waveform_output_initializing = false;
        return false;
    }
#endif

    /* 只有所有编译启用的后端均成功后才对上层发布整体就绪。 */
    waveform_output_initialized = true;
    waveform_output_initializing = false;
    WaveformOutputDebugSend(
        ready_message, sizeof(ready_message) - 1U);
    return true;
#endif
}

bool WaveformOutputStopAll(void)
{
#if APP_ENABLE_WAVEFORM_OUTPUT == 0U
    return true;
#else
    /* 即使某个后端停止失败，也继续尝试关闭其余输出并汇总结果。 */
    bool result = true;

    if (!waveform_output_initialized) {
        return true;
    }
#if APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U
    result = DDSOutputStop() && result;
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U
    result = AD9850OutputStop() && result;
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    result = DACOutputStop() && result;
#endif
    return result;
#endif
}

bool WaveformOutputIsInitialized(void)
{
#if APP_ENABLE_WAVEFORM_OUTPUT != 0U
    return waveform_output_initialized;
#else
    return false;
#endif
}

bool WaveformOutputBackendIsEnabled(
    WaveformOutputBackend_e backend)
{
    switch (backend) {
        case WAVEFORM_OUTPUT_BACKEND_DAC:
            return (APP_ENABLE_WAVEFORM_OUTPUT != 0U) &&
                   (APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U);

        case WAVEFORM_OUTPUT_BACKEND_DDS:
            return (APP_ENABLE_WAVEFORM_OUTPUT != 0U) &&
                   (APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U);

        case WAVEFORM_OUTPUT_BACKEND_AD9850:
            return (APP_ENABLE_WAVEFORM_OUTPUT != 0U) &&
                   (APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U);

        default:
            return false;
    }
}

bool WaveformOutputDACSetRaw(uint16_t raw_value)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    return waveform_output_initialized &&
           DACOutputSetRaw(raw_value);
#else
    (void)raw_value;
    return false;
#endif
}

bool WaveformOutputDACSetMillivolts(uint16_t millivolts)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    return waveform_output_initialized &&
           DACOutputSetMillivolts(millivolts);
#else
    (void)millivolts;
    return false;
#endif
}

bool WaveformOutputDACSetPercent(uint8_t percent)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    return waveform_output_initialized &&
           DACOutputSetPercent(percent);
#else
    (void)percent;
    return false;
#endif
}

bool WaveformOutputDACConfigure(
    const WaveformOutputDACConfig *config)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    DACOutputWaveformConfig module_config;

    return waveform_output_initialized &&
           WaveformOutputConvertDACConfig(config, &module_config) &&
           DACOutputConfigureWaveform(&module_config);
#else
    (void)config;
    return false;
#endif
}

uint32_t WaveformOutputDACGetMaximumFrequencyHz(
    WaveformOutputDACMode_e mode)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    switch (mode) {
        case WAVEFORM_OUTPUT_DAC_MODE_SINE:
            return DACOutputGetMaximumFrequencyHz(
                DAC_OUTPUT_MODE_SINE);
        case WAVEFORM_OUTPUT_DAC_MODE_SQUARE:
            return DACOutputGetMaximumFrequencyHz(
                DAC_OUTPUT_MODE_SQUARE);
        case WAVEFORM_OUTPUT_DAC_MODE_TRIANGLE:
            return DACOutputGetMaximumFrequencyHz(
                DAC_OUTPUT_MODE_TRIANGLE);
        case WAVEFORM_OUTPUT_DAC_MODE_SAWTOOTH:
            return DACOutputGetMaximumFrequencyHz(
                DAC_OUTPUT_MODE_SAWTOOTH);
        default:
            return 0UL;
    }
#else
    (void)mode;
    return 0UL;
#endif
}

bool WaveformOutputDACStart(void)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    return waveform_output_initialized && DACOutputStart();
#else
    return false;
#endif
}

bool WaveformOutputDACStop(void)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    return waveform_output_initialized && DACOutputStop();
#else
    return false;
#endif
}

bool WaveformOutputDACGetRaw(uint16_t *raw_value)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    return waveform_output_initialized &&
           DACOutputGetRaw(raw_value);
#else
    (void)raw_value;
    return false;
#endif
}

bool WaveformOutputDACGetMillivolts(uint16_t *millivolts)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    return waveform_output_initialized &&
           DACOutputGetMillivolts(millivolts);
#else
    (void)millivolts;
    return false;
#endif
}

bool WaveformOutputDACIsEnabled(void)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    return waveform_output_initialized && DACOutputIsEnabled();
#else
    return false;
#endif
}

WaveformOutputDACMode_e WaveformOutputDACGetMode(void)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    switch (DACOutputGetMode()) {
        case DAC_OUTPUT_MODE_STOPPED:
            return WAVEFORM_OUTPUT_DAC_MODE_STOPPED;
        case DAC_OUTPUT_MODE_DC:
            return WAVEFORM_OUTPUT_DAC_MODE_DC;
        case DAC_OUTPUT_MODE_SINE:
            return WAVEFORM_OUTPUT_DAC_MODE_SINE;
        case DAC_OUTPUT_MODE_SQUARE:
            return WAVEFORM_OUTPUT_DAC_MODE_SQUARE;
        case DAC_OUTPUT_MODE_TRIANGLE:
            return WAVEFORM_OUTPUT_DAC_MODE_TRIANGLE;
        case DAC_OUTPUT_MODE_SAWTOOTH:
            return WAVEFORM_OUTPUT_DAC_MODE_SAWTOOTH;
        case DAC_OUTPUT_MODE_CUSTOM:
            /* 任意波形仍由 DAC 后端播放；上层槽位服务单独提供元数据。 */
            return WAVEFORM_OUTPUT_DAC_MODE_CUSTOM;
        default:
            return WAVEFORM_OUTPUT_DAC_MODE_STOPPED;
    }
#else
    return WAVEFORM_OUTPUT_DAC_MODE_STOPPED;
#endif
}

bool WaveformOutputDACGetConfig(WaveformOutputDACConfig *config)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    DACOutputWaveformConfig module_config;

    if (!waveform_output_initialized || (config == NULL) ||
        !DACOutputGetWaveformConfig(&module_config)) {
        return false;
    }

    switch (module_config.mode) {
        case DAC_OUTPUT_MODE_SINE:
            config->mode = WAVEFORM_OUTPUT_DAC_MODE_SINE;
            break;
        case DAC_OUTPUT_MODE_SQUARE:
            config->mode = WAVEFORM_OUTPUT_DAC_MODE_SQUARE;
            break;
        case DAC_OUTPUT_MODE_TRIANGLE:
            config->mode = WAVEFORM_OUTPUT_DAC_MODE_TRIANGLE;
            break;
        case DAC_OUTPUT_MODE_SAWTOOTH:
            config->mode = WAVEFORM_OUTPUT_DAC_MODE_SAWTOOTH;
            break;
        default:
            return false;
    }
    config->frequency_hz = module_config.frequency_hz;
    config->minimum_millivolts = module_config.minimum_millivolts;
    config->maximum_millivolts = module_config.maximum_millivolts;
    return true;
#else
    (void)config;
    return false;
#endif
}

uint32_t WaveformOutputDACGetActualFrequencyMillihz(void)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    return waveform_output_initialized
               ? DACOutputGetActualFrequencyMillihz()
               : 0UL;
#else
    return 0UL;
#endif
}

uint32_t WaveformOutputDACGetFIFOunderrunCount(void)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    return waveform_output_initialized
               ? DACOutputGetFIFOunderrunCount()
               : 0UL;
#else
    return 0UL;
#endif
}

uint32_t WaveformOutputDACGetStreamRefillMissCount(void)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    return waveform_output_initialized
               ? DACOutputGetStreamRefillMissCount()
               : 0UL;
#else
    return 0UL;
#endif
}

bool WaveformOutputDDSSetFrequency(uint32_t frequency_hz)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U
    return waveform_output_initialized &&
           DDSOutputSetFrequency(frequency_hz);
#else
    (void)frequency_hz;
    return false;
#endif
}

bool WaveformOutputDDSSetPhase(uint16_t phase_degrees)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U
    return waveform_output_initialized &&
           DDSOutputSetPhase(phase_degrees);
#else
    (void)phase_degrees;
    return false;
#endif
}

bool WaveformOutputDDSSetWaveform(
    WaveformOutputDDSWaveform_e waveform)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U
    DDSOutputWaveform_e module_waveform;

    return waveform_output_initialized &&
           WaveformOutputConvertDDSWaveform(
               waveform, &module_waveform) &&
           DDSOutputSetWaveform(module_waveform);
#else
    (void)waveform;
    return false;
#endif
}

bool WaveformOutputDDSStart(void)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U
    return waveform_output_initialized && DDSOutputStart();
#else
    return false;
#endif
}

bool WaveformOutputDDSStop(void)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U
    return waveform_output_initialized && DDSOutputStop();
#else
    return false;
#endif
}

bool WaveformOutputDDSGetState(WaveformOutputDDSState *state)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U
    DDSOutputState module_state;

    if (!waveform_output_initialized || (state == NULL) ||
        !DDSOutputGetState(&module_state)) {
        return false;
    }

    switch (module_state.waveform) {
        case DDS_OUTPUT_WAVEFORM_SINE:
            state->waveform = WAVEFORM_OUTPUT_DDS_WAVEFORM_SINE;
            break;
        case DDS_OUTPUT_WAVEFORM_TRIANGLE:
            state->waveform = WAVEFORM_OUTPUT_DDS_WAVEFORM_TRIANGLE;
            break;
        case DDS_OUTPUT_WAVEFORM_SQUARE:
            state->waveform = WAVEFORM_OUTPUT_DDS_WAVEFORM_SQUARE;
            break;
        default:
            return false;
    }

    state->frequency_hz  = module_state.frequency_hz;
    state->phase_degrees = module_state.phase_degrees;
    state->enabled       = module_state.enabled;
    return true;
#else
    (void)state;
    return false;
#endif
}

bool WaveformOutputAD9850SetFrequency(uint32_t frequency_hz)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U
    return waveform_output_initialized &&
           (frequency_hz >= WAVEFORM_OUTPUT_AD9850_MINIMUM_FREQUENCY_HZ) &&
           (frequency_hz <= APP_AD9850_MAXIMUM_FREQUENCY_HZ) &&
           AD9850OutputSetFrequency(frequency_hz);
#else
    (void)frequency_hz;
    return false;
#endif
}

bool WaveformOutputAD9850SetWaveform(
    WaveformOutputAD9850Waveform_e waveform)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U
    AD9850OutputWaveform_e module_waveform;

    return waveform_output_initialized &&
           WaveformOutputConvertAD9850Waveform(waveform, &module_waveform) &&
           AD9850OutputSetWaveform(module_waveform);
#else
    (void)waveform;
    return false;
#endif
}

bool WaveformOutputAD9850Start(void)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U
    return waveform_output_initialized && AD9850OutputStart();
#else
    return false;
#endif
}

bool WaveformOutputAD9850Stop(void)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U
    return waveform_output_initialized && AD9850OutputStop();
#else
    return false;
#endif
}

bool WaveformOutputAD9850GetState(WaveformOutputAD9850State *state)
{
#if APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U
    AD9850OutputState module_state;

    if (!waveform_output_initialized || (state == NULL) ||
        !AD9850OutputGetState(&module_state)) {
        return false;
    }
    state->frequency_hz = module_state.frequency_hz;
    state->enabled = module_state.enabled;
    state->waveform = (module_state.waveform == AD9850_OUTPUT_WAVEFORM_SINE)
                          ? WAVEFORM_OUTPUT_AD9850_WAVEFORM_SINE
                          : WAVEFORM_OUTPUT_AD9850_WAVEFORM_SQUARE;
    return true;
#else
    (void)state;
    return false;
#endif
}

#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
/* Application 枚举与 Module 枚举显式转换，拒绝停止、直流和自定义模式。 */
static bool WaveformOutputConvertDACConfig(
    const WaveformOutputDACConfig *source,
    DACOutputWaveformConfig *destination)
{
    if ((source == NULL) || (destination == NULL)) {
        return false;
    }

    switch (source->mode) {
        case WAVEFORM_OUTPUT_DAC_MODE_SINE:
            destination->mode = DAC_OUTPUT_MODE_SINE;
            break;
        case WAVEFORM_OUTPUT_DAC_MODE_SQUARE:
            destination->mode = DAC_OUTPUT_MODE_SQUARE;
            break;
        case WAVEFORM_OUTPUT_DAC_MODE_TRIANGLE:
            destination->mode = DAC_OUTPUT_MODE_TRIANGLE;
            break;
        case WAVEFORM_OUTPUT_DAC_MODE_SAWTOOTH:
            destination->mode = DAC_OUTPUT_MODE_SAWTOOTH;
            break;
        default:
            return false;
    }

    destination->frequency_hz = source->frequency_hz;
    destination->minimum_millivolts =
        source->minimum_millivolts;
    destination->maximum_millivolts =
        source->maximum_millivolts;
    return true;
}
#endif

#if APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U
static bool WaveformOutputConvertAD9850Waveform(
    WaveformOutputAD9850Waveform_e source,
    AD9850OutputWaveform_e *destination)
{
    if (destination == NULL) {
        return false;
    }
    switch (source) {
        case WAVEFORM_OUTPUT_AD9850_WAVEFORM_SINE:
            *destination = AD9850_OUTPUT_WAVEFORM_SINE;
            return true;
        case WAVEFORM_OUTPUT_AD9850_WAVEFORM_SQUARE:
            *destination = AD9850_OUTPUT_WAVEFORM_SQUARE;
            return true;
        default:
            return false;
    }
}
#endif

#if APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U
static bool WaveformOutputConvertDDSWaveform(
    WaveformOutputDDSWaveform_e source,
    DDSOutputWaveform_e *destination)
{
    if (destination == NULL) {
        return false;
    }

    switch (source) {
        case WAVEFORM_OUTPUT_DDS_WAVEFORM_SINE:
            *destination = DDS_OUTPUT_WAVEFORM_SINE;
            return true;
        case WAVEFORM_OUTPUT_DDS_WAVEFORM_TRIANGLE:
            *destination = DDS_OUTPUT_WAVEFORM_TRIANGLE;
            return true;
        case WAVEFORM_OUTPUT_DDS_WAVEFORM_SQUARE:
            *destination = DDS_OUTPUT_WAVEFORM_SQUARE;
            return true;
        default:
            return false;
    }
}
#endif

#if APP_ENABLE_WAVEFORM_OUTPUT != 0U
static void WaveformOutputDebugSend(
    const uint8_t *data, size_t size)
{
    if (WAVEFORM_OUTPUT_DEBUG_OUTPUT_ENABLED != 0U) {
        (void)SerialCommunicationUART0Send(data, size);
    }
}
#endif
