/* ADC 采样门面：用统一输入编号向业务层提供异步采集能力。 */
#ifndef ADC_SAMPLING_H
#define ADC_SAMPLING_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    /* PA27 / ADC0.0。 */
    ADC_SAMPLING_INPUT_PA27 = 0,
    /* PB19 / ADC1.6。 */
    ADC_SAMPLING_INPUT_PB19,
    /* 兼容旧调用名：当前硬件实际为 PB19 / ADC1.6。 */
    ADC_SAMPLING_INPUT_PA21 = ADC_SAMPLING_INPUT_PB19,
    ADC_SAMPLING_INPUT_COUNT
} ADCSamplingInput_e;

/** 一次性直接 DMA 采集完成回调；在 DMA ISR 中执行。 */
typedef void (*ADCSamplingDirectCaptureCallback_t)(
    ADCSamplingInput_e input, uint32_t sequence, void *context);

typedef enum {
    /* DMA 已采满目标点数。 */
    ADC_SAMPLING_THRESHOLD_CAPTURE_COMPLETE = 0,
    /* 输入已回落到低阈值，硬件已具备再次触发条件。 */
    ADC_SAMPLING_THRESHOLD_SIGNAL_REARMED
} ADCSamplingThresholdEvent_e;

/** 阈值采集事件回调；在 ADC/DMA ISR 中执行。 */
typedef void (*ADCSamplingThresholdCaptureCallback_t)(
    ADCSamplingInput_e input, ADCSamplingThresholdEvent_e event,
    uint32_t sequence, void *context);

/** 两路配对 DMA 都完成后的回调；在 DMA ISR 中执行。 */
typedef void (*ADCSamplingSynchronizedCaptureCallback_t)(
    uint32_t sequence, void *context);

/** 注册指定 ADC 输入；仅准备资源，不启动采样。 */
bool ADCSamplingInitInput(ADCSamplingInput_e input);

/** 按指定采样率一次性采集连续 sample_count 点。 */
bool ADCSamplingStartDirectInputCapture(ADCSamplingInput_e input,
    uint16_t *buffer, size_t buffer_capacity, size_t sample_count,
    uint32_t sample_rate_hz,
    ADCSamplingDirectCaptureCallback_t callback, void *context);

/** PA27 先由 ADC12 窗口比较器触发，再由 DMA 采满指定点数。 */
bool ADCSamplingStartThresholdInputCapture(ADCSamplingInput_e input,
    uint16_t *buffer, size_t buffer_capacity, size_t sample_count,
    uint32_t sample_rate_hz, uint16_t high_threshold_raw,
    uint16_t low_threshold_raw,
    ADCSamplingThresholdCaptureCallback_t callback, void *context);

/**
 * 同步启动 PA27 与 PA21 的一次性配对采集。
 * PA21 为兼容旧调用名，当前第二路硬件实际连接 PB19 / ADC1.6。
 * first_buffer[i] 与 second_buffer[i] 属于同一采样时刻。
 */
bool ADCSamplingStartSynchronizedCapture(
    uint16_t *first_buffer, size_t first_buffer_capacity,
    uint16_t *second_buffer, size_t second_buffer_capacity,
    size_t sample_count, uint32_t sample_rate_hz,
    ADCSamplingSynchronizedCaptureCallback_t callback, void *context);

/** 结束或中止当前两路配对采集。 */
bool ADCSamplingFinishSynchronizedCapture(void);

/** 返回当前是否有两路配对采集正在执行。 */
bool ADCSamplingIsSynchronizedCaptureActive(void);

/** 结束或中止本次采集；结束后保持停止，不恢复旧流式模式。 */
bool ADCSamplingFinishDirectInputCapture(ADCSamplingInput_e input);

/** 结束阈值触发采集并释放 ADC。 */
bool ADCSamplingFinishThresholdInputCapture(ADCSamplingInput_e input);

/** 将已取得的 ADC 原始值按指定输入的参考电压换算为毫伏。 */
bool ADCSamplingConvertRawToMillivolts(ADCSamplingInput_e input,
    uint16_t raw_value, uint16_t *millivolts);

/** 返回指定输入是否正在执行一次性 DMA。 */
bool ADCSamplingIsDirectInputCaptureActive(ADCSamplingInput_e input);

/** 返回指定输入的阈值触发链路是否仍占用 ADC。 */
bool ADCSamplingIsThresholdInputCaptureActive(ADCSamplingInput_e input);

/** 返回板级默认采样率，当前为 1 MHz。 */
uint32_t ADCSamplingGetSampleRateHz(void);

/** 判断一次性 DMA 是否支持指定采样频率。 */
bool ADCSamplingIsSampleRateSupported(uint32_t sample_rate_hz);

#endif
