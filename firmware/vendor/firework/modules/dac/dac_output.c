/*
 * DACOutput 使用固定采样率相位累加器生成标准/任意波形，并以双缓冲任务持续回填 DMA。
 */
#include "modules/dac/dac_output.h"

#include "application/app_config.h"

#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U

#include <stddef.h>

#include "FreeRTOS.h"
#include "semphr.h"
#include "task.h"

#include "modules/dac/dac.h"

#define DAC_OUTPUT_DEFAULT_RAW_VALUE          (0U)
#define DAC_OUTPUT_REFERENCE_MILLIVOLTS       (3300U)
#define DAC_OUTPUT_MAXIMUM_RAW_VALUE          (4095U)
#define DAC_OUTPUT_TABLE_CAPACITY             (1024U)
#define DAC_OUTPUT_SMOOTH_MINIMUM_SAMPLES_PER_CYCLE (16U)
#define DAC_OUTPUT_SQUARE_MINIMUM_SAMPLES_PER_CYCLE (2U)
#define DAC_OUTPUT_HALF_PHASE                 (UINT32_C(0x80000000))
#define DAC_OUTPUT_SINE_TABLE_SIZE            (32U)
#define DAC_OUTPUT_WAVEFORM_TABLE_SIZE        (1024U)
#define DAC_OUTPUT_WAVEFORM_PHASE_SHIFT       (22U)
#define DAC_OUTPUT_SINE_INTERPOLATION_STEPS   (32U)

/* 一个完整周期的 (sin(x)+1)/2，使用 0～65535 无符号比例保存。 */
static const uint16_t dac_output_sine_table[
    DAC_OUTPUT_SINE_TABLE_SIZE] = {
    32768U, 39160U, 45307U, 50972U, 55938U, 60013U, 63041U, 64905U,
    65535U, 64905U, 63041U, 60013U, 55938U, 50972U, 45307U, 39160U,
    32768U, 26375U, 20228U, 14563U, 9597U, 5522U, 2494U, 630U,
    0U, 630U, 2494U, 5522U, 9597U, 14563U, 20228U, 26375U
};

/*
 * 两个半缓冲区必须在内存中连续排列。DMA 以重复模式循环整个2048点区域，
 * 半程/完成中断分别释放前后半区，从而避免在块边界由CPU重装DMA造成欠载。
 * 任意波形的调用方缓冲区仍使用前1024点。
 */
static uint16_t dac_output_stream_samples[
    DAC_OUTPUT_TABLE_CAPACITY * 2U];
static uint16_t dac_output_waveform_table[
    DAC_OUTPUT_WAVEFORM_TABLE_SIZE];
static DACInstance *dac_output;
static DACOutputMode_e dac_output_mode = DAC_OUTPUT_MODE_STOPPED;
static DACOutputWaveformConfig dac_waveform_config;
static uint32_t dac_output_actual_frequency_millihz;
static bool dac_output_initialized;
static SemaphoreHandle_t dac_output_mutex;
static StaticSemaphore_t dac_output_mutex_control;
static TaskHandle_t dac_output_refill_task_handle;
static uint16_t *volatile dac_output_pending_refill_samples;
static volatile uint16_t dac_output_pending_refill_count;
static volatile uint32_t dac_output_waveform_next_phase;
static volatile uint32_t dac_output_waveform_phase_increment;
#if APP_DAC_SQUARE_FORCE_INTEGER_EVEN_SAMPLES != 0U
static volatile uint32_t dac_output_square_sample_index;
static uint32_t dac_output_square_half_period_samples;
static uint16_t dac_output_square_minimum_raw;
static uint16_t dac_output_square_maximum_raw;
static bool dac_output_square_stable_period;
#endif

static bool DACOutputLock(void);
static void DACOutputUnlock(void);
static bool DACOutputSetDCModeLocked(void);
static bool DACOutputStartWaveformLocked(
    const DACOutputWaveformConfig *config);
static bool DACOutputStartCustomWaveformLocked(uint16_t sample_count,
    uint32_t sample_rate_hz, uint16_t cycle_count);
static bool DACOutputWaveformConfigIsValid(
    const DACOutputWaveformConfig *config);
static void DACOutputSynchronizeHardwareStateLocked(void);
static uint16_t DACOutputGetMinimumSamplesPerCycle(
    DACOutputMode_e mode);
static void DACOutputBuildWaveformTable(
    const DACOutputWaveformConfig *config);
static void DACOutputFillWaveformBuffer(
    uint16_t *samples, uint16_t sample_count, void *context);
static void DACOutputRequestWaveformBufferRefillFromISR(
    uint16_t *samples, uint16_t sample_count, void *context);
static void DACOutputDiscardPendingRefillLocked(void);
static uint16_t DACOutputMillivoltsToRaw(uint16_t millivolts);
static uint16_t DACOutputCalculateWaveformRaw(
    DACOutputMode_e mode, uint32_t phase,
    uint16_t minimum_raw, uint16_t maximum_raw);

/* 注册 PA15 / DAC0；周期波形完全由硬件 Sample Timer + DMA 输出。 */
bool DACOutputInit(void)
{
    static const DACConfig config = {
        DAC_OUTPUT_DEFAULT_RAW_VALUE,
        false
    };

    if (dac_output_initialized) {
        return true;
    }

    if (dac_output_mutex == NULL) {
        dac_output_mutex =
            xSemaphoreCreateMutexStatic(&dac_output_mutex_control);
        if (dac_output_mutex == NULL) {
            return false;
        }
    }

    if (dac_output == NULL) {
        dac_output = DACRegister(DAC_DEVICE_OUTPUT_0, &config);
        if (dac_output == NULL) {
            return false;
        }
    }

    dac_output_mode = DAC_OUTPUT_MODE_STOPPED;
    dac_output_actual_frequency_millihz = 0UL;
    dac_output_initialized = true;
    return true;
}

bool DACOutputSetRaw(uint16_t raw_value)
{
    bool result;

    if (!DACOutputLock()) {
        return false;
    }
    result = (raw_value <= DAC_OUTPUT_MAXIMUM_RAW_VALUE) &&
             DACWriteRaw(dac_output, raw_value);
    if (result) {
        DACOutputDiscardPendingRefillLocked();
        dac_output_mode = DAC_OUTPUT_MODE_DC;
        dac_output_actual_frequency_millihz = 0UL;
    }
    DACOutputUnlock();
    return result;
}

bool DACOutputSetMillivolts(uint16_t millivolts)
{
    bool result;

    if (!DACOutputLock()) {
        return false;
    }
    result = (millivolts <= DAC_OUTPUT_REFERENCE_MILLIVOLTS) &&
             DACWriteMillivolts(dac_output, millivolts);
    if (result) {
        DACOutputDiscardPendingRefillLocked();
        dac_output_mode = DAC_OUTPUT_MODE_DC;
        dac_output_actual_frequency_millihz = 0UL;
    }
    DACOutputUnlock();
    return result;
}

bool DACOutputSetPercent(uint8_t percent)
{
    bool result;

    if (!DACOutputLock()) {
        return false;
    }
    result = DACWritePercent(dac_output, percent);
    if (result) {
        DACOutputDiscardPendingRefillLocked();
        dac_output_mode = DAC_OUTPUT_MODE_DC;
        dac_output_actual_frequency_millihz = 0UL;
    }
    DACOutputUnlock();
    return result;
}

/* 四种内置周期波形统一使用固定采样率连续 DDS。 */
bool DACOutputConfigureWaveform(
    const DACOutputWaveformConfig *config)
{
    bool result;

    if (!DACOutputWaveformConfigIsValid(config) ||
        !DACOutputLock()) {
        return false;
    }

    result = DACStopWaveform(dac_output);
    if (result) {
        DACOutputDiscardPendingRefillLocked();
        result = DACOutputStartWaveformLocked(config);
    }
    if (result) {
        dac_waveform_config = *config;
        dac_output_mode = config->mode;
    } else {
        dac_output_mode = DAC_OUTPUT_MODE_STOPPED;
        dac_output_actual_frequency_millihz = 0UL;
        (void)DACStop(dac_output);
        DACOutputDiscardPendingRefillLocked();
    }

    DACOutputUnlock();
    return result;
}

bool DACOutputStart(void)
{
    bool result;

    if (!DACOutputLock()) {
        return false;
    }
    result = DACOutputSetDCModeLocked();
    DACOutputUnlock();
    return result;
}

bool DACOutputStop(void)
{
    bool result;

    if (!DACOutputLock()) {
        return false;
    }
    result = DACStop(dac_output);
    if (result) {
        DACOutputDiscardPendingRefillLocked();
        dac_output_mode = DAC_OUTPUT_MODE_STOPPED;
        dac_output_actual_frequency_millihz = 0UL;
    }
    DACOutputUnlock();
    return result;
}

bool DACOutputGetRaw(uint16_t *raw_value)
{
    bool result;

    if (!DACOutputLock()) {
        return false;
    }
    result = DACGetRawValue(dac_output, raw_value);
    DACOutputUnlock();
    return result;
}

bool DACOutputGetMillivolts(uint16_t *millivolts)
{
    bool result;

    if (!DACOutputLock()) {
        return false;
    }
    result = DACGetMillivolts(dac_output, millivolts);
    DACOutputUnlock();
    return result;
}

bool DACOutputIsEnabled(void)
{
    bool enabled;

    if (!DACOutputLock()) {
        return false;
    }
    DACOutputSynchronizeHardwareStateLocked();
    enabled = DACIsEnabled(dac_output);
    DACOutputUnlock();
    return enabled;
}

bool DACOutputIsInitialized(void)
{
    return dac_output_initialized;
}

DACOutputMode_e DACOutputGetMode(void)
{
    DACOutputMode_e mode;

    if (!DACOutputLock()) {
        return DAC_OUTPUT_MODE_STOPPED;
    }
    DACOutputSynchronizeHardwareStateLocked();
    mode = dac_output_mode;
    DACOutputUnlock();
    return mode;
}

bool DACOutputGetWaveformConfig(DACOutputWaveformConfig *config)
{
    bool result;

    if ((config == NULL) || !DACOutputLock()) {
        return false;
    }
    DACOutputSynchronizeHardwareStateLocked();
    result = (dac_output_mode == DAC_OUTPUT_MODE_SINE) ||
             (dac_output_mode == DAC_OUTPUT_MODE_SQUARE) ||
             (dac_output_mode == DAC_OUTPUT_MODE_TRIANGLE) ||
             (dac_output_mode == DAC_OUTPUT_MODE_SAWTOOTH);
    if (result) {
        *config = dac_waveform_config;
    }
    DACOutputUnlock();
    return result;
}

uint32_t DACOutputGetActualFrequencyMillihz(void)
{
    uint32_t frequency_millihz;

    if (!DACOutputLock()) {
        return 0UL;
    }
    DACOutputSynchronizeHardwareStateLocked();
    frequency_millihz = dac_output_actual_frequency_millihz;
    DACOutputUnlock();
    return frequency_millihz;
}

uint32_t DACOutputGetFIFOunderrunCount(void)
{
    uint32_t underrun_count = 0UL;

    if (!DACOutputLock()) {
        return 0UL;
    }
    (void)DACGetFIFOunderrunCount(dac_output, &underrun_count);
    DACOutputUnlock();
    return underrun_count;
}

uint32_t DACOutputGetStreamRefillMissCount(void)
{
    uint32_t miss_count = 0UL;

    if (!DACOutputLock()) {
        return 0UL;
    }
    (void)DACGetStreamRefillMissCount(dac_output, &miss_count);
    DACOutputUnlock();
    return miss_count;
}

bool DACOutputSetRefillTaskHandle(TaskHandle_t task_handle)
{
    bool result;

    if (!dac_output_initialized || (task_handle == NULL)) {
        return false;
    }
    taskENTER_CRITICAL();
    result = (dac_output_refill_task_handle == NULL) ||
             (dac_output_refill_task_handle == task_handle);
    if (result) {
        dac_output_refill_task_handle = task_handle;
    }
    taskEXIT_CRITICAL();
    return result;
}

void DACOutputRefillTask(void *argument)
{
    (void)argument;

    for (;;) {
        (void)ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

        if (DACOutputLock()) {
            uint16_t *samples;
            uint16_t sample_count;

            taskENTER_CRITICAL();
            samples = dac_output_pending_refill_samples;
            sample_count = dac_output_pending_refill_count;
            dac_output_pending_refill_samples = NULL;
            dac_output_pending_refill_count = 0U;
            taskEXIT_CRITICAL();

            if ((samples != NULL) && (sample_count > 0U) &&
                DACIsWaveformRunning(dac_output)) {
                DACOutputFillWaveformBuffer(
                    samples, sample_count, NULL);
                (void)DACCommitStreamingBuffer(dac_output, samples);
            }
            DACOutputUnlock();
        }
    }
}

static void DACOutputSynchronizeHardwareStateLocked(void)
{
    if ((dac_output_mode >= DAC_OUTPUT_MODE_SINE) &&
        (dac_output_mode <= DAC_OUTPUT_MODE_CUSTOM) &&
        !DACIsWaveformRunning(dac_output)) {
        DACOutputDiscardPendingRefillLocked();
        dac_output_mode = DAC_OUTPUT_MODE_STOPPED;
        dac_output_actual_frequency_millihz = 0UL;
    }
}

uint16_t *DACOutputGetCustomWaveformBuffer(void)
{
    return dac_output_initialized ? dac_output_stream_samples : NULL;
}

uint16_t DACOutputGetCustomWaveformCapacity(void)
{
    return DAC_OUTPUT_TABLE_CAPACITY;
}

bool DACOutputStartCustomWaveform(uint16_t sample_count,
    uint32_t sample_rate_hz, uint16_t cycle_count)
{
    bool result;

    if ((sample_count < 2U) ||
        (sample_count > DAC_OUTPUT_TABLE_CAPACITY) ||
        (cycle_count == 0U) || !DACOutputLock()) {
        return false;
    }

    result = DACOutputStartCustomWaveformLocked(sample_count,
        sample_rate_hz, cycle_count);
    DACOutputUnlock();
    return result;
}

uint32_t DACOutputGetMaximumFrequencyHz(DACOutputMode_e mode)
{
    uint32_t software_limit;
    uint32_t fixed_rate_limit;
    uint16_t minimum_samples_per_cycle =
        DACOutputGetMinimumSamplesPerCycle(mode);

    switch (mode) {
        case DAC_OUTPUT_MODE_SINE:
            software_limit = DAC_OUTPUT_SINE_MAXIMUM_FREQUENCY_HZ;
            break;
        case DAC_OUTPUT_MODE_SQUARE:
            software_limit = DAC_OUTPUT_SQUARE_MAXIMUM_FREQUENCY_HZ;
            break;
        case DAC_OUTPUT_MODE_TRIANGLE:
            software_limit = DAC_OUTPUT_TRIANGLE_MAXIMUM_FREQUENCY_HZ;
            break;
        case DAC_OUTPUT_MODE_SAWTOOTH:
            software_limit = DAC_OUTPUT_SAWTOOTH_MAXIMUM_FREQUENCY_HZ;
            break;
        default:
            return 0UL;
    }

    fixed_rate_limit = APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ /
                       minimum_samples_per_cycle;
    return (fixed_rate_limit < software_limit)
               ? fixed_rate_limit
               : software_limit;
}

static bool DACOutputLock(void)
{
    return dac_output_initialized && (dac_output != NULL) &&
           (dac_output_mutex != NULL) &&
           (xSemaphoreTake(dac_output_mutex, portMAX_DELAY) == pdPASS);
}

static void DACOutputUnlock(void)
{
    (void)xSemaphoreGive(dac_output_mutex);
}

static bool DACOutputSetDCModeLocked(void)
{
    bool result = DACStart(dac_output);

    if (result) {
        DACOutputDiscardPendingRefillLocked();
        dac_output_mode = DAC_OUTPUT_MODE_DC;
        dac_output_actual_frequency_millihz = 0UL;
    }
    return result;
}

/*
 * 内置周期波形共用固定采样率的32位相位累加器。两个1024点缓冲区由 DMA
 * 交替输出，并在高优先级任务中回填，因此低频周期可以跨越多个缓冲区。
 */
static bool DACOutputStartWaveformLocked(
    const DACOutputWaveformConfig *config)
{
    uint64_t phase_increment_numerator;
    bool result;

    if ((config == NULL) || (dac_output_refill_task_handle == NULL)) {
        return false;
    }

#if APP_DAC_SQUARE_FORCE_INTEGER_EVEN_SAMPLES != 0U
    dac_output_square_stable_period =
        config->mode == DAC_OUTPUT_MODE_SQUARE;
    if (dac_output_square_stable_period) {
        uint64_t doubled_frequency =
            (uint64_t)config->frequency_hz * 2ULL;

        dac_output_square_half_period_samples = (uint32_t)(
            ((uint64_t)APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ +
                config->frequency_hz) /
            doubled_frequency);
        if (dac_output_square_half_period_samples == 0UL) {
            dac_output_square_half_period_samples = 1UL;
        }
        dac_output_square_sample_index = 0UL;
        dac_output_square_minimum_raw =
            DACOutputMillivoltsToRaw(config->minimum_millivolts);
        dac_output_square_maximum_raw =
            DACOutputMillivoltsToRaw(config->maximum_millivolts);
    }
#endif

    phase_increment_numerator =
        ((uint64_t)config->frequency_hz << 32U) +
        (APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ / 2UL);
    dac_output_waveform_phase_increment = (uint32_t)(
        phase_increment_numerator /
        APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ);
    if (dac_output_waveform_phase_increment == 0UL) {
        return false;
    }

#if APP_DAC_SQUARE_FORCE_INTEGER_EVEN_SAMPLES != 0U
    if (!dac_output_square_stable_period)
#endif
    {
        DACOutputBuildWaveformTable(config);
    }
    dac_output_waveform_next_phase = 0UL;
    DACOutputFillWaveformBuffer(dac_output_stream_samples,
        DAC_OUTPUT_TABLE_CAPACITY, NULL);
    DACOutputFillWaveformBuffer(
        &dac_output_stream_samples[DAC_OUTPUT_TABLE_CAPACITY],
        DAC_OUTPUT_TABLE_CAPACITY, NULL);

    result = DACStartStreamingWaveform(dac_output,
        dac_output_stream_samples,
        &dac_output_stream_samples[DAC_OUTPUT_TABLE_CAPACITY],
        DAC_OUTPUT_TABLE_CAPACITY,
        APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ,
        DACOutputRequestWaveformBufferRefillFromISR, NULL);
    if (result) {
#if APP_DAC_SQUARE_FORCE_INTEGER_EVEN_SAMPLES != 0U
        if (dac_output_square_stable_period) {
            dac_output_actual_frequency_millihz = (uint32_t)(
                (((uint64_t)APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ *
                     1000ULL) +
                    dac_output_square_half_period_samples) /
                (2ULL * dac_output_square_half_period_samples));
        } else
#endif
        {
            dac_output_actual_frequency_millihz = (uint32_t)(
                ((((uint64_t)dac_output_waveform_phase_increment *
                       APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ * 1000ULL) +
                     (UINT64_C(1) << 31U)) >>
                    32U));
        }
    }
    return result;
}

static bool DACOutputStartCustomWaveformLocked(uint16_t sample_count,
    uint32_t sample_rate_hz, uint16_t cycle_count)
{
    uint64_t phase_increment_denominator;
    uint64_t phase_increment_numerator;
    uint64_t phase_increment_value;
    uint16_t index;
    bool result;

    result = DACStopWaveform(dac_output);
    if (!result) {
        return false;
    }
    DACOutputDiscardPendingRefillLocked();
    if (dac_output_refill_task_handle == NULL) {
        return false;
    }

    /* 先保存调用方写入第一块 DMA 缓冲区的原始波形，再复用该缓冲区输出。 */
    for (index = 0U;
         index < DAC_OUTPUT_WAVEFORM_TABLE_SIZE;
         ++index) {
        uint16_t source_index = (uint16_t)(
            ((uint32_t)index * sample_count) /
            DAC_OUTPUT_WAVEFORM_TABLE_SIZE);

        dac_output_waveform_table[index] =
            dac_output_stream_samples[source_index];
    }

    /* 相位完整走一圈的时间保持为原始 sample_count / sample_rate_hz。 */
    phase_increment_denominator =
        (uint64_t)sample_count *
        APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ;
    phase_increment_numerator =
        ((uint64_t)sample_rate_hz << 32U) +
        (phase_increment_denominator / 2ULL);
    phase_increment_value =
        phase_increment_numerator / phase_increment_denominator;
    if ((phase_increment_value == 0ULL) ||
        (phase_increment_value > UINT32_MAX)) {
        return false;
    }
    dac_output_waveform_phase_increment =
        (uint32_t)phase_increment_value;

#if APP_DAC_SQUARE_FORCE_INTEGER_EVEN_SAMPLES != 0U
    dac_output_square_stable_period = false;
#endif
    dac_output_waveform_next_phase = 0UL;
    DACOutputFillWaveformBuffer(dac_output_stream_samples,
        DAC_OUTPUT_TABLE_CAPACITY, NULL);
    DACOutputFillWaveformBuffer(
        &dac_output_stream_samples[DAC_OUTPUT_TABLE_CAPACITY],
        DAC_OUTPUT_TABLE_CAPACITY, NULL);
    result = DACStartStreamingWaveform(dac_output,
        dac_output_stream_samples,
        &dac_output_stream_samples[DAC_OUTPUT_TABLE_CAPACITY],
        DAC_OUTPUT_TABLE_CAPACITY,
        APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ,
        DACOutputRequestWaveformBufferRefillFromISR, NULL);

    if (result) {
        dac_output_mode = DAC_OUTPUT_MODE_CUSTOM;
        dac_output_actual_frequency_millihz = (uint32_t)(
            (((uint64_t)cycle_count * sample_rate_hz * 1000ULL) +
                (sample_count / 2U)) / sample_count);
    } else {
        dac_output_mode = DAC_OUTPUT_MODE_STOPPED;
        dac_output_actual_frequency_millihz = 0UL;
    }
    return result;
}

static bool DACOutputWaveformConfigIsValid(
    const DACOutputWaveformConfig *config)
{
    uint32_t maximum_frequency_hz;

    if (config == NULL) {
        return false;
    }
    maximum_frequency_hz =
        DACOutputGetMaximumFrequencyHz(config->mode);
    return (maximum_frequency_hz != 0UL) &&
           (config->frequency_hz >= DAC_OUTPUT_MINIMUM_FREQUENCY_HZ) &&
           (config->frequency_hz <= maximum_frequency_hz) &&
           (config->minimum_millivolts < config->maximum_millivolts) &&
           (config->maximum_millivolts <=
               DAC_OUTPUT_REFERENCE_MILLIVOLTS);
}

static uint16_t DACOutputGetMinimumSamplesPerCycle(
    DACOutputMode_e mode)
{
    switch (mode) {
        case DAC_OUTPUT_MODE_SQUARE:
            return DAC_OUTPUT_SQUARE_MINIMUM_SAMPLES_PER_CYCLE;
        case DAC_OUTPUT_MODE_SINE:
        case DAC_OUTPUT_MODE_TRIANGLE:
        case DAC_OUTPUT_MODE_SAWTOOTH:
            return DAC_OUTPUT_SMOOTH_MINIMUM_SAMPLES_PER_CYCLE;
        default:
            return 0U;
    }
}

/*
 * 为当前波形预生成1024级相位表，并提前缩放到当前电压上下限。
 * 高优先级回填任务只需查表和累加相位，不做乘除法。
 */
static void DACOutputBuildWaveformTable(
    const DACOutputWaveformConfig *config)
{
    uint16_t minimum_raw =
        DACOutputMillivoltsToRaw(config->minimum_millivolts);
    uint16_t maximum_raw =
        DACOutputMillivoltsToRaw(config->maximum_millivolts);
    uint16_t index;

    for (index = 0U;
         index < DAC_OUTPUT_WAVEFORM_TABLE_SIZE;
         ++index) {
        uint32_t phase =
            (uint32_t)index << DAC_OUTPUT_WAVEFORM_PHASE_SHIFT;

        dac_output_waveform_table[index] =
            DACOutputCalculateWaveformRaw(config->mode,
                phase, minimum_raw, maximum_raw);
    }
}

/* 在 DACRefill 任务中运行：每完成 1024 个固定采样率输出点调用一次。 */
static void DACOutputFillWaveformBuffer(
    uint16_t *samples, uint16_t sample_count, void *context)
{
    uint32_t phase = dac_output_waveform_next_phase;
    uint16_t index;

    (void)context;
    if (samples == NULL) {
        return;
    }

#if APP_DAC_SQUARE_FORCE_INTEGER_EVEN_SAMPLES != 0U
    if (dac_output_square_stable_period) {
        uint32_t square_index = dac_output_square_sample_index;
        uint32_t period_samples =
            dac_output_square_half_period_samples * 2UL;

        for (index = 0U; index < sample_count; ++index) {
            samples[index] =
                (square_index < dac_output_square_half_period_samples)
                    ? dac_output_square_minimum_raw
                    : dac_output_square_maximum_raw;
            ++square_index;
            if (square_index >= period_samples) {
                square_index = 0UL;
            }
        }
        dac_output_square_sample_index = square_index;
        return;
    }
#endif

    for (index = 0U; index < sample_count; ++index) {
        samples[index] = dac_output_waveform_table[
            phase >> DAC_OUTPUT_WAVEFORM_PHASE_SHIFT];
        phase += dac_output_waveform_phase_increment;
    }
    dac_output_waveform_next_phase = phase;
}

/* DAC ISR 只发布空闲缓冲区，1024点查表工作由高优先级任务完成。 */
static void DACOutputRequestWaveformBufferRefillFromISR(
    uint16_t *samples, uint16_t sample_count, void *context)
{
    BaseType_t higher_priority_task_woken = pdFALSE;
    UBaseType_t interrupt_state;

    (void)context;
    if ((samples == NULL) || (sample_count == 0U) ||
        (dac_output_refill_task_handle == NULL)) {
        return;
    }

    interrupt_state = taskENTER_CRITICAL_FROM_ISR();
    if (dac_output_pending_refill_samples == NULL) {
        dac_output_pending_refill_samples = samples;
        dac_output_pending_refill_count = sample_count;
    }
    taskEXIT_CRITICAL_FROM_ISR(interrupt_state);
    vTaskNotifyGiveFromISR(dac_output_refill_task_handle,
        &higher_priority_task_woken);
    portYIELD_FROM_ISR(higher_priority_task_woken);
}

static void DACOutputDiscardPendingRefillLocked(void)
{
    taskENTER_CRITICAL();
    dac_output_pending_refill_samples = NULL;
    dac_output_pending_refill_count = 0U;
    taskEXIT_CRITICAL();
}

static uint16_t DACOutputMillivoltsToRaw(uint16_t millivolts)
{
    return (uint16_t)((
        ((uint32_t)millivolts * DAC_OUTPUT_MAXIMUM_RAW_VALUE) +
        (DAC_OUTPUT_REFERENCE_MILLIVOLTS / 2U)) /
        DAC_OUTPUT_REFERENCE_MILLIVOLTS);
}

static uint16_t DACOutputCalculateWaveformRaw(
    DACOutputMode_e mode, uint32_t phase,
    uint16_t minimum_raw, uint16_t maximum_raw)
{
    uint32_t range = (uint32_t)maximum_raw - minimum_raw;
    uint64_t scaled_offset;

    switch (mode) {
        case DAC_OUTPUT_MODE_SINE: {
            uint32_t table_index = phase >> 27U;
            uint32_t next_index =
                (table_index + 1U) % DAC_OUTPUT_SINE_TABLE_SIZE;
            uint32_t fraction =
                (phase >> DAC_OUTPUT_WAVEFORM_PHASE_SHIFT) &
                (DAC_OUTPUT_SINE_INTERPOLATION_STEPS - 1U);
            uint32_t normalized =
                ((uint32_t)dac_output_sine_table[table_index] *
                     (DAC_OUTPUT_SINE_INTERPOLATION_STEPS - fraction) +
                 (uint32_t)dac_output_sine_table[next_index] * fraction +
                 (DAC_OUTPUT_SINE_INTERPOLATION_STEPS / 2U)) /
                DAC_OUTPUT_SINE_INTERPOLATION_STEPS;

            scaled_offset = (uint64_t)range * normalized;
            return (uint16_t)(minimum_raw +
                ((scaled_offset + (UINT16_MAX / 2U)) /
                    UINT16_MAX));
        }

        case DAC_OUTPUT_MODE_SQUARE:
            return (phase < DAC_OUTPUT_HALF_PHASE)
                       ? minimum_raw
                       : maximum_raw;

        case DAC_OUTPUT_MODE_TRIANGLE:
            if (phase < DAC_OUTPUT_HALF_PHASE) {
                scaled_offset = (uint64_t)range * phase * 2U;
            } else {
                scaled_offset =
                    (uint64_t)range * (UINT32_MAX - phase) * 2U;
            }
            break;

        case DAC_OUTPUT_MODE_SAWTOOTH:
            scaled_offset = (uint64_t)range * phase;
            break;

        default:
            return minimum_raw;
    }

    return (uint16_t)(minimum_raw +
        (scaled_offset / UINT32_MAX));
}

#endif /* APP_ENABLE_WAVEFORM_OUTPUT_DAC */
