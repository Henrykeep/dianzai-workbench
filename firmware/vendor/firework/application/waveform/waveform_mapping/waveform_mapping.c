/*
 * 波形映射是测量结果到输出后端之间的桥梁：收到完整测量结果后，
 * 先校验波形类型和频率，再转换成当前配置后端能够接受的输出参数。
 */
#include "application/waveform/waveform_mapping/waveform_mapping.h"

#include <limits.h>
#include <stddef.h>

#include "application/app_config.h"

#if APP_ENABLE_WAVEFORM_MAPPING != 0U

#include "application/communication/serial_communication/serial_communication.h"
#include "application/waveform/waveform_measurement/waveform_measurement.h"
#include "application/waveform/waveform_output/waveform_output.h"

#define WAVEFORM_MAPPING_DEBUG_OUTPUT_ENABLED (1U)

/* 回调在测量发布上下文中更新最近状态和序号，读取接口只提供轻量快照。 */
static bool waveform_mapping_initialized;
static volatile WaveformMappingStatus_e waveform_mapping_status =
    WAVEFORM_MAPPING_STATUS_UNINITIALIZED;
static volatile uint32_t waveform_mapping_last_sequence;

#if APP_ENABLE_WAVEFORM_MAPPING != 0U
/* 只消费 PA27 的完整测量结果，其他输入由各自业务独立处理。 */
static void WaveformMappingResultReady(
    WaveformMeasurementInput_e input,
    const WaveformMeasurement *measurement, void *context);
/* 先做跨后端公共校验，再交给编译期唯一选中的输出后端。 */
static bool WaveformMappingApply(
    const WaveformMeasurement *measurement);
/* 测量值以 mHz 保存，这里四舍五入为输出后端使用的整数 Hz。 */
static bool WaveformMappingGetFrequencyHz(
    const WaveformMeasurement *measurement, uint32_t *frequency_hz);
static void WaveformMappingSetFailure(
    WaveformMappingStatus_e status);
static void WaveformMappingDebugSend(
    const uint8_t *data, size_t size);

#if APP_WAVEFORM_MAPPING_BACKEND_DAC != 0U
static bool WaveformMappingApplyDAC(
    const WaveformMeasurement *measurement);
#elif APP_WAVEFORM_MAPPING_BACKEND_AD9833 != 0U
static bool WaveformMappingApplyAD9833(
    const WaveformMeasurement *measurement);
#else
static bool WaveformMappingApplyAD9850(
    const WaveformMeasurement *measurement);
#endif

#endif /* APP_ENABLE_WAVEFORM_MAPPING */

bool WaveformMappingInit(void)
{
#if APP_ENABLE_WAVEFORM_MAPPING == 0U
    return false;
#else
#if APP_WAVEFORM_MAPPING_BACKEND_DAC != 0U
    static const uint8_t ready_message[] =
        "WAVEFORM MAPPING READY PA27 DAC\r\n";
#elif APP_WAVEFORM_MAPPING_BACKEND_AD9833 != 0U
    static const uint8_t ready_message[] =
        "WAVEFORM MAPPING READY PA27 AD9833\r\n";
#else
    static const uint8_t ready_message[] =
        "WAVEFORM MAPPING READY PA27 AD9850\r\n";
#endif

    if (waveform_mapping_initialized) {
        return true;
    }
    if (!WaveformOutputIsInitialized() ||
        !WaveformMeasurementIsInputEnabled(
            WAVEFORM_MEASUREMENT_INPUT_PA27) ||
        !WaveformMeasurementSubscribeResultReady(
            WaveformMappingResultReady, NULL)) {
        return false;
    }

    waveform_mapping_status = WAVEFORM_MAPPING_STATUS_READY;
    waveform_mapping_initialized = true;
    WaveformMappingDebugSend(
        ready_message, sizeof(ready_message) - 1U);
    return true;
#endif
}

bool WaveformMappingIsInitialized(void)
{
    return waveform_mapping_initialized;
}

WaveformMappingStatus_e WaveformMappingGetStatus(void)
{
    return waveform_mapping_status;
}

uint32_t WaveformMappingGetLastSequence(void)
{
    return waveform_mapping_last_sequence;
}

bool WaveformMappingStop(void)
{
#if APP_ENABLE_WAVEFORM_MAPPING == 0U
    return true;
#elif APP_WAVEFORM_MAPPING_BACKEND_DAC != 0U
    return WaveformOutputDACStop();
#elif APP_WAVEFORM_MAPPING_BACKEND_AD9833 != 0U
    return WaveformOutputDDSStop();
#else
    return WaveformOutputAD9850Stop();
#endif
}

#if APP_ENABLE_WAVEFORM_MAPPING != 0U
static void WaveformMappingResultReady(
    WaveformMeasurementInput_e input,
    const WaveformMeasurement *measurement, void *context)
{
    (void)context;

    if (!waveform_mapping_initialized ||
        (input != WAVEFORM_MEASUREMENT_INPUT_PA27) ||
        (measurement == NULL)) {
        return;
    }

    waveform_mapping_last_sequence = measurement->sequence;
    if (WaveformMappingApply(measurement)) {
        static const uint8_t applied_message[] =
            "WAVEFORM MAPPING APPLIED\r\n";

        waveform_mapping_status = WAVEFORM_MAPPING_STATUS_APPLIED;
        WaveformMappingDebugSend(
            applied_message, sizeof(applied_message) - 1U);
    }
}

static bool WaveformMappingApply(
    const WaveformMeasurement *measurement)
{
    bool waveform_type_valid;

    if ((measurement == NULL) ||
        (measurement->source != WAVEFORM_MEASUREMENT_INPUT_PA27)) {
        WaveformMappingSetFailure(
            WAVEFORM_MAPPING_STATUS_INVALID_RESULT);
        return false;
    }
    waveform_type_valid =
        (measurement->valid_mask &
            WAVEFORM_MEASUREMENT_VALID_WAVEFORM_TYPE) != 0UL;
    if (!waveform_type_valid) {
        WaveformMappingSetFailure(
            WAVEFORM_MAPPING_STATUS_INVALID_RESULT);
        return false;
    }

#if APP_WAVEFORM_MAPPING_BACKEND_DAC != 0U
    return WaveformMappingApplyDAC(measurement);
#elif APP_WAVEFORM_MAPPING_BACKEND_AD9833 != 0U
    return WaveformMappingApplyAD9833(measurement);
#else
    return WaveformMappingApplyAD9850(measurement);
#endif
}

static bool WaveformMappingGetFrequencyHz(
    const WaveformMeasurement *measurement, uint32_t *frequency_hz)
{
    uint64_t rounded_frequency;

    if ((measurement == NULL) || (frequency_hz == NULL) ||
        ((measurement->valid_mask &
             WAVEFORM_MEASUREMENT_VALID_FREQUENCY) == 0UL) ||
        (measurement->frequency_millihz == 0UL)) {
        return false;
    }

    rounded_frequency =
        ((uint64_t)measurement->frequency_millihz + 500ULL) /
        1000ULL;
    if ((rounded_frequency == 0ULL) ||
        (rounded_frequency > UINT32_MAX)) {
        return false;
    }
    *frequency_hz = (uint32_t)rounded_frequency;
    return true;
}

#if APP_WAVEFORM_MAPPING_BACKEND_DAC != 0U
static bool WaveformMappingApplyDAC(
    const WaveformMeasurement *measurement)
{
    WaveformOutputDACConfig config;
    uint32_t frequency_hz;
    uint32_t maximum_frequency_hz;

    if (measurement->waveform_type ==
        WAVEFORM_MEASUREMENT_WAVEFORM_DC) {
        if ((measurement->valid_mask &
                WAVEFORM_MEASUREMENT_VALID_AVERAGE) == 0UL) {
            WaveformMappingSetFailure(
                WAVEFORM_MAPPING_STATUS_INVALID_RESULT);
            return false;
        }
        if (!WaveformOutputDACSetMillivolts(
                measurement->average_millivolts)) {
            WaveformMappingSetFailure(
                WAVEFORM_MAPPING_STATUS_OUTPUT_ERROR);
            return false;
        }
        return true;
    }

    switch (measurement->waveform_type) {
        case WAVEFORM_MEASUREMENT_WAVEFORM_SINE:
            config.mode = WAVEFORM_OUTPUT_DAC_MODE_SINE;
            break;
        case WAVEFORM_MEASUREMENT_WAVEFORM_SQUARE:
            config.mode = WAVEFORM_OUTPUT_DAC_MODE_SQUARE;
            break;
        case WAVEFORM_MEASUREMENT_WAVEFORM_TRIANGLE:
            config.mode = WAVEFORM_OUTPUT_DAC_MODE_TRIANGLE;
            break;
        case WAVEFORM_MEASUREMENT_WAVEFORM_SAWTOOTH:
            config.mode = WAVEFORM_OUTPUT_DAC_MODE_SAWTOOTH;
            break;
        default:
            WaveformMappingSetFailure(
                WAVEFORM_MAPPING_STATUS_UNSUPPORTED_WAVEFORM);
            return false;
    }

    if (!WaveformMappingGetFrequencyHz(measurement, &frequency_hz)) {
        WaveformMappingSetFailure(
            WAVEFORM_MAPPING_STATUS_FREQUENCY_OUT_OF_RANGE);
        return false;
    }
    maximum_frequency_hz =
        WaveformOutputDACGetMaximumFrequencyHz(config.mode);
    if (maximum_frequency_hz == 0UL) {
        WaveformMappingSetFailure(
            WAVEFORM_MAPPING_STATUS_UNSUPPORTED_WAVEFORM);
        return false;
    }
    /* DAC 查表输出超过软件上限时降到该波形可稳定生成的最高频率。 */
    if (frequency_hz > maximum_frequency_hz) {
        frequency_hz = maximum_frequency_hz;
    }
    if (((measurement->valid_mask &
             WAVEFORM_MEASUREMENT_VALID_MINIMUM) == 0UL) ||
        ((measurement->valid_mask &
             WAVEFORM_MEASUREMENT_VALID_MAXIMUM) == 0UL) ||
        (measurement->minimum_millivolts >=
            measurement->maximum_millivolts)) {
        WaveformMappingSetFailure(
            WAVEFORM_MAPPING_STATUS_INVALID_RESULT);
        return false;
    }

    config.frequency_hz = frequency_hz;
    config.minimum_millivolts = measurement->minimum_millivolts;
    config.maximum_millivolts = measurement->maximum_millivolts;
    if (!WaveformOutputDACStop() ||
        !WaveformOutputDACConfigure(&config)) {
        WaveformMappingSetFailure(
            WAVEFORM_MAPPING_STATUS_OUTPUT_ERROR);
        return false;
    }
    return true;
}
#elif APP_WAVEFORM_MAPPING_BACKEND_AD9833 != 0U
static bool WaveformMappingApplyAD9833(
    const WaveformMeasurement *measurement)
{
    WaveformOutputDDSWaveform_e waveform;
    uint32_t frequency_hz;

    switch (measurement->waveform_type) {
        case WAVEFORM_MEASUREMENT_WAVEFORM_SINE:
            waveform = WAVEFORM_OUTPUT_DDS_WAVEFORM_SINE;
            break;
        case WAVEFORM_MEASUREMENT_WAVEFORM_TRIANGLE:
            waveform = WAVEFORM_OUTPUT_DDS_WAVEFORM_TRIANGLE;
            break;
        case WAVEFORM_MEASUREMENT_WAVEFORM_SQUARE:
            waveform = WAVEFORM_OUTPUT_DDS_WAVEFORM_SQUARE;
            break;
        default:
            WaveformMappingSetFailure(
                WAVEFORM_MAPPING_STATUS_UNSUPPORTED_WAVEFORM);
            return false;
    }

    if (!WaveformMappingGetFrequencyHz(measurement, &frequency_hz)) {
        WaveformMappingSetFailure(
            WAVEFORM_MAPPING_STATUS_FREQUENCY_OUT_OF_RANGE);
        return false;
    }

    if (!WaveformOutputDDSStop() ||
        !WaveformOutputDDSSetWaveform(waveform) ||
        !WaveformOutputDDSSetFrequency(frequency_hz) ||
        !WaveformOutputDDSSetPhase(0U) ||
        !WaveformOutputDDSStart()) {
        WaveformMappingSetFailure(
            WAVEFORM_MAPPING_STATUS_OUTPUT_ERROR);
        return false;
    }
    return true;
}
#else
/* AD9850 模块板的 SIN/SQ 是两条独立物理输出，不能生成三角波或直流。 */
static bool WaveformMappingApplyAD9850(
    const WaveformMeasurement *measurement)
{
    WaveformOutputAD9850Waveform_e waveform;
    uint32_t frequency_hz;

    switch (measurement->waveform_type) {
        case WAVEFORM_MEASUREMENT_WAVEFORM_SINE:
            waveform = WAVEFORM_OUTPUT_AD9850_WAVEFORM_SINE;
            break;
        case WAVEFORM_MEASUREMENT_WAVEFORM_SQUARE:
            waveform = WAVEFORM_OUTPUT_AD9850_WAVEFORM_SQUARE;
            break;
        default:
            WaveformMappingSetFailure(
                WAVEFORM_MAPPING_STATUS_UNSUPPORTED_WAVEFORM);
            return false;
    }

    if (!WaveformMappingGetFrequencyHz(measurement, &frequency_hz) ||
        (frequency_hz > APP_AD9850_MAXIMUM_FREQUENCY_HZ)) {
        WaveformMappingSetFailure(
            WAVEFORM_MAPPING_STATUS_FREQUENCY_OUT_OF_RANGE);
        return false;
    }

    if (!WaveformOutputAD9850Stop() ||
        !WaveformOutputAD9850SetWaveform(waveform) ||
        !WaveformOutputAD9850SetFrequency(frequency_hz) ||
        !WaveformOutputAD9850Start()) {
        WaveformMappingSetFailure(
            WAVEFORM_MAPPING_STATUS_OUTPUT_ERROR);
        return false;
    }
    return true;
}
#endif

/* 任一映射错误都先停止旧输出，避免继续输出与最新测量不一致的波形。 */
static void WaveformMappingSetFailure(
    WaveformMappingStatus_e status)
{
    static const uint8_t error_message[] =
        "WAVEFORM MAPPING SKIPPED\r\n";

    (void)WaveformMappingStop();
    waveform_mapping_status = status;
    WaveformMappingDebugSend(
        error_message, sizeof(error_message) - 1U);
}

static void WaveformMappingDebugSend(
    const uint8_t *data, size_t size)
{
    if (WAVEFORM_MAPPING_DEBUG_OUTPUT_ENABLED != 0U) {
        (void)SerialCommunicationUART0Send(data, size);
    }
}
#endif

#endif /* APP_ENABLE_WAVEFORM_MAPPING */
