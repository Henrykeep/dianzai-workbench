/* ADC 硬件无关接口：提供直接、阈值触发及双通道同步采集。 */
#ifndef ADC_H
#define ADC_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    /* PA27 / ADC0.0。 */
    ADC_DEVICE_INPUT_0 = 0,
    /* PB19 / ADC1.6。 */
    ADC_DEVICE_INPUT_1,
    /* 逻辑 ADC 设备数量，同时作为枚举范围上限。 */
    ADC_DEVICE_COUNT
} ADC_Device_e;

/** ADC 模块的不透明实例。 */
typedef struct ADCInstance ADCInstance;

/** 一次性直接 DMA 采集完成回调；由 DMA ISR 调用。 */
typedef void (*ADCDirectCaptureCallback_t)(
    uint32_t sequence, void *context);

typedef enum {
    /* DMA 已采满目标点数。 */
    ADC_THRESHOLD_CAPTURE_COMPLETE = 0,
    /* 输入已回落到低阈值，可开始下一次触发。 */
    ADC_THRESHOLD_SIGNAL_REARMED
} ADCThresholdEvent_e;

/** 阈值采集事件回调；在 ADC/DMA ISR 中执行。 */
typedef void (*ADCThresholdCaptureCallback_t)(
    ADCThresholdEvent_e event, uint32_t sequence, void *context);

/** 两路 ADC 配对 DMA 都完成后的回调。 */
typedef void (*ADCSynchronizedCaptureCallback_t)(
    uint32_t sequence, void *context);

/** 注册 ADC 设备并创建线程安全访问所需的互斥锁。 */
ADCInstance *ADCRegister(ADC_Device_e device);

/** 按指定采样率一次性采集连续 sample_count 点。 */
bool ADCStartDirectCapture(ADCInstance *instance,
    uint16_t *buffer, size_t buffer_capacity, size_t sample_count,
    uint32_t sample_rate_hz,
    ADCDirectCaptureCallback_t callback, void *context);

/** 启动 ADC12 窗口比较器触发、DMA 采满及回落重武装链路。 */
bool ADCStartThresholdTriggeredCapture(
    ADCInstance *instance, uint16_t *buffer, size_t buffer_capacity,
    size_t sample_count, uint32_t sample_rate_hz,
    uint16_t high_threshold_raw, uint16_t low_threshold_raw,
    ADCThresholdCaptureCallback_t callback, void *context);

/** 同步启动 ADC0/ADC1 的共享定时器配对采集。 */
bool ADCStartSynchronizedCapture(
    ADCInstance *first_instance, uint16_t *first_buffer,
    size_t first_buffer_capacity, ADCInstance *second_instance,
    uint16_t *second_buffer, size_t second_buffer_capacity,
    size_t sample_count, uint32_t sample_rate_hz,
    ADCSynchronizedCaptureCallback_t callback, void *context);

/** 结束或中止当前配对采集。 */
bool ADCFinishSynchronizedCapture(void);

/** 返回当前是否有配对采集仍在执行。 */
bool ADCIsSynchronizedCaptureActive(void);

/** 结束或中止一次性采集，结束后不自动启动其他采样模式。 */
bool ADCFinishDirectCapture(ADCInstance *instance);

/** 中止当前 ADC12 窗口比较器触发链路。 */
bool ADCFinishThresholdTriggeredCapture(ADCInstance *instance);

/** 返回一次性 DMA 当前是否仍在采集。 */
bool ADCIsDirectCaptureActive(const ADCInstance *instance);

/** 返回阈值触发链路是否仍占用该 ADC。 */
bool ADCIsThresholdTriggeredCaptureActive(const ADCInstance *instance);

/** 返回板级默认采样率，当前为 1 MHz。 */
uint32_t ADCGetDefaultSampleRateHz(const ADCInstance *instance);

/** 判断板级低速定时或高速 FIFO 路径是否支持该采样率。 */
bool ADCIsSampleRateSupported(uint32_t sample_rate_hz);

/** 将已经取得的原始值换算成毫伏。 */
bool ADCConvertRawToMillivolts(
    ADCInstance *instance, uint16_t raw_value, uint16_t *millivolts);

#endif
