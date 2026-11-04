/**
 * @file waveform_measurement.h
 * @brief ADC/串口波形采集、参数计算、FFT 和结果订阅接口。
 *
 * 本模块把“采集窗口”和“测量结果”分开：采集完成后统一计算，再通知显示和输出模块。
 */
#ifndef WAVEFORM_MEASUREMENT_H
#define WAVEFORM_MEASUREMENT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** 波形参数测量的独立输入。 */
typedef enum {
    WAVEFORM_MEASUREMENT_INPUT_PA27 = 0,
    WAVEFORM_MEASUREMENT_INPUT_PB19,
    /* 兼容旧调用名：当前硬件实际为 PB19 / ADC1.6。 */
    WAVEFORM_MEASUREMENT_INPUT_PA21 =
        WAVEFORM_MEASUREMENT_INPUT_PB19,
    WAVEFORM_MEASUREMENT_INPUT_COUNT
} WaveformMeasurementInput_e;

/** 波形结果中各字段的有效位。 */
typedef enum {
    WAVEFORM_MEASUREMENT_VALID_MINIMUM = (1UL << 0U),
    WAVEFORM_MEASUREMENT_VALID_MAXIMUM = (1UL << 1U),
    WAVEFORM_MEASUREMENT_VALID_PEAK_TO_PEAK = (1UL << 2U),
    WAVEFORM_MEASUREMENT_VALID_AVERAGE = (1UL << 3U),
    WAVEFORM_MEASUREMENT_VALID_FREQUENCY = (1UL << 4U),
    WAVEFORM_MEASUREMENT_VALID_PERIOD = (1UL << 5U),
    WAVEFORM_MEASUREMENT_VALID_DUTY_CYCLE = (1UL << 6U),
    WAVEFORM_MEASUREMENT_VALID_WAVEFORM_TYPE = (1UL << 7U)
} WaveformMeasurementValidMask_e;

/** 根据本次 ADC 样本和频谱估算的基础波形类型。 */
typedef enum {
    WAVEFORM_MEASUREMENT_WAVEFORM_UNKNOWN = 0,
    WAVEFORM_MEASUREMENT_WAVEFORM_DC,
    WAVEFORM_MEASUREMENT_WAVEFORM_SINE,
    WAVEFORM_MEASUREMENT_WAVEFORM_SQUARE,
    WAVEFORM_MEASUREMENT_WAVEFORM_TRIANGLE,
    WAVEFORM_MEASUREMENT_WAVEFORM_SAWTOOTH,
    WAVEFORM_MEASUREMENT_WAVEFORM_HARMONIC
} WaveformMeasurementWaveformType_e;

/** 频率和周期采用的测量来源。 */
typedef enum {
    WAVEFORM_MEASUREMENT_FREQUENCY_SOURCE_NONE = 0,
    WAVEFORM_MEASUREMENT_FREQUENCY_SOURCE_CAPTURE,
    /** 兼容旧调试值；当前实现不再发布 ADC 边沿频率。 */
    WAVEFORM_MEASUREMENT_FREQUENCY_SOURCE_ADC_EDGES,
    WAVEFORM_MEASUREMENT_FREQUENCY_SOURCE_FFT
} WaveformMeasurementFrequencySource_e;

/** 一份波形快照的整体状态。 */
typedef enum {
    WAVEFORM_MEASUREMENT_STATUS_NOT_READY = 0,
    WAVEFORM_MEASUREMENT_STATUS_PARTIAL,
    WAVEFORM_MEASUREMENT_STATUS_VALID,
    WAVEFORM_MEASUREMENT_STATUS_NO_SIGNAL
} WaveformMeasurementStatus_e;

/** 一次按键测量请求的执行状态。 */
typedef enum {
    WAVEFORM_MEASUREMENT_REQUEST_IDLE = 0,
    WAVEFORM_MEASUREMENT_REQUEST_COLLECTING,
    WAVEFORM_MEASUREMENT_REQUEST_COMPLETE,
    WAVEFORM_MEASUREMENT_REQUEST_START_FAILED,
    WAVEFORM_MEASUREMENT_REQUEST_TIMEOUT,
    WAVEFORM_MEASUREMENT_REQUEST_FFT_FAILED,
    WAVEFORM_MEASUREMENT_REQUEST_CALCULATION_FAILED
} WaveformMeasurementRequestStatus_e;

/** 双路同步主频相位测量状态。 */
typedef enum {
    WAVEFORM_SYNCHRONIZED_PHASE_STATUS_NOT_READY = 0,
    WAVEFORM_SYNCHRONIZED_PHASE_STATUS_VALID,
    WAVEFORM_SYNCHRONIZED_PHASE_STATUS_NO_SIGNAL,
    WAVEFORM_SYNCHRONIZED_PHASE_STATUS_FREQUENCY_MISMATCH,
    WAVEFORM_SYNCHRONIZED_PHASE_STATUS_CALCULATION_FAILED
} WaveformSynchronizedPhaseStatus_e;

/**
 * 同一输入引脚的 ADC、FFT 与 COMP 捕获结果组成的波形参数。
 * 电压单位为 mV，频率单位为 mHz，周期单位为 us，占空比单位为万分之一；
 * valid_mask 指明哪些字段可用，sequence 每次成功发布后递增。
 */
typedef struct {
    uint16_t minimum_millivolts;
    uint16_t maximum_millivolts;
    uint16_t peak_to_peak_millivolts;
    uint16_t average_millivolts;
    uint32_t frequency_millihz;
    uint32_t period_microseconds;
    uint16_t duty_cycle_permyriad;
    uint32_t valid_mask;
    uint32_t timestamp_ticks;
    uint32_t sequence;
    uint32_t sample_rate_hz;
    uint16_t sample_count;
    uint32_t frequency_scale_numerator;
    uint32_t frequency_scale_denominator;
    WaveformMeasurementInput_e source;
    WaveformMeasurementWaveformType_e waveform_type;
    WaveformMeasurementFrequencySource_e frequency_source;
    WaveformMeasurementStatus_e status;
} WaveformMeasurement;

/**
 * 同一 DMA 触发窗口内 PB19 相对 PA27 的主频相位差。
 * phase_millidegrees 范围为 -180000～180000；正值表示 PB19 超前 PA27。
 */
typedef struct {
    int32_t phase_millidegrees;
    uint32_t frequency_millihz;
    uint32_t timestamp_ticks;
    uint32_t sequence;
    uint32_t source_sequence;
    uint32_t sample_rate_hz;
    uint16_t sample_count;
    uint16_t common_peak_bin;
    uint16_t pa27_peak_magnitude;
    uint16_t pb19_peak_magnitude;
    WaveformSynchronizedPhaseStatus_e status;
} WaveformSynchronizedPhaseMeasurement;

/**
 * 测量结果发布观察者；普通请求在 Waveform Measurement 任务上下文执行，
 * 外部样本分析接口则在调用它的任务上下文执行。
 */
typedef void (*WaveformMeasurementResultReadyCallback_t)(
    WaveformMeasurementInput_e input,
    const WaveformMeasurement *measurement, void *context);

/** CCS Debug Watch 可观察的测量诊断计数；下标 0 为 PA27，下标 1 为 PA21。 */
extern volatile WaveformMeasurementRequestStatus_e
    waveform_measurement_request_statuses[
        WAVEFORM_MEASUREMENT_INPUT_COUNT];
extern volatile uint32_t waveform_measurement_last_progress_ticks[
    WAVEFORM_MEASUREMENT_INPUT_COUNT];
extern volatile uint32_t waveform_measurement_accepted_block_counts[
    WAVEFORM_MEASUREMENT_INPUT_COUNT];
extern volatile uint32_t waveform_measurement_rejected_block_counts[
    WAVEFORM_MEASUREMENT_INPUT_COUNT];

/** CCS Debug Watch 可直接观察的最近一次同步相位结果。 */
extern volatile WaveformSynchronizedPhaseMeasurement
    waveform_measurement_synchronized_phase_result;

/** 返回指定输入最近一次测量请求状态。 */
WaveformMeasurementRequestStatus_e WaveformMeasurementGetRequestStatus(
    WaveformMeasurementInput_e input);

/** 准备已选输入、FFT、Capture 和测量任务；PA27/PA21 保持停止。 */
bool WaveformMeasurementInit(void);

/**
 * 分析外部提供的 PA27/PA21 ADC 样本并发布统一测量结果。
 *
 * 时域参数使用完整 sample_count；FFT 使用不超过 sample_count 的最近
 * 支持点数（64/128/256/512/1024/2048）。不足 64 点时，FFT 输入会用最后
 * 一个真实样本补齐到 64 点；结果中的 sample_count 仍是实际采样点数。
 * 该接口在调用任务上下文中完成分析并发布结果，适合阈值触发采样等外部
 * DMA 数据源。
 */
bool WaveformMeasurementAnalyzeExternalSamples(
    WaveformMeasurementInput_e input, const uint16_t *samples,
    size_t sample_count, uint32_t sample_rate_hz,
    uint32_t source_sequence);

/**
 * 请求指定输入按 app_config.h 的点数和频率完成一次测量。
 * 启用 APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE 时，会同时采集 PA27/PA21，
 * 并分别更新两路结果；请求的输入只决定当前菜单等待和读取哪一路结果。
 */
bool WaveformMeasurementRequestInput(
    WaveformMeasurementInput_e input);

/** 发起一次双路同步采集，并在完成后发布 PB19 相对 PA27 的相位差。 */
bool WaveformMeasurementRequestSynchronizedPhase(void);

/** 复制最近一次双路同步相位结果。 */
bool WaveformMeasurementCopyLatestSynchronizedPhase(
    WaveformSynchronizedPhaseMeasurement *measurement);

/** 返回指定输入的单次测量采样点数；同步模式下两路均返回公共点数。 */
size_t WaveformMeasurementGetInputSampleCount(
    WaveformMeasurementInput_e input);

/** 返回指定输入的有效采样频率；同步模式下两路均返回公共采样率。 */
uint32_t WaveformMeasurementGetInputSampleRateHz(
    WaveformMeasurementInput_e input);

/** 返回指定输入的前级频率换算分子。 */
uint32_t WaveformMeasurementGetInputFrequencyScaleNumerator(
    WaveformMeasurementInput_e input);

/** 返回指定输入的前级频率换算分母。 */
uint32_t WaveformMeasurementGetInputFrequencyScaleDenominator(
    WaveformMeasurementInput_e input);

/** 将前级输出端实测频率换算为原始输入频率，单位均为 mHz。 */
bool WaveformMeasurementScaleInputFrequencyMillihz(
    WaveformMeasurementInput_e input,
    uint32_t measured_frequency_millihz,
    uint32_t *input_frequency_millihz);

/** 返回指定输入是否正在执行一次测量请求。 */
bool WaveformMeasurementIsInputPending(
    WaveformMeasurementInput_e input);

/** 返回指定输入是否由当前编译配置启用。 */
bool WaveformMeasurementIsInputEnabled(
    WaveformMeasurementInput_e input);

/** 设置兼容读取接口的默认输入，不影响另一路测量。 */
bool WaveformMeasurementSetInput(
    WaveformMeasurementInput_e input);

/** 返回兼容读取接口的当前默认输入。 */
WaveformMeasurementInput_e WaveformMeasurementGetInput(void);

/** 复制默认输入最近发布的波形参数。 */
bool WaveformMeasurementCopyLatest(
    WaveformMeasurement *measurement);

/** 复制指定输入最近发布的独立波形参数。 */
bool WaveformMeasurementCopyLatestInput(
    WaveformMeasurementInput_e input,
    WaveformMeasurement *measurement);

/**
 * 分段复制指定结果最后最多 128 个 ADC 原始样本。
 * 仅在该输入没有正在测量且 result_sequence 与最新结果一致时成功。
 * offset 必须落在 sample_count - 128 到 sample_count - 1 的保留区间。
 */
bool WaveformMeasurementCopyLatestInputSamples(
    WaveformMeasurementInput_e input, uint32_t result_sequence,
    size_t offset, uint16_t *samples, size_t capacity,
    size_t *copied_count);

/** 注册测量结果观察者；相同 callback/context 重复注册视为成功。 */
bool WaveformMeasurementSubscribeResultReady(
    WaveformMeasurementResultReadyCallback_t callback,
    void *context);

/** 移除先前注册的测量结果观察者。 */
bool WaveformMeasurementUnsubscribeResultReady(
    WaveformMeasurementResultReadyCallback_t callback,
    void *context);

/** 返回是否至少有一路 PA27/PA21 正在执行一次测量请求。 */
bool WaveformMeasurementIsRunning(void);

#endif
