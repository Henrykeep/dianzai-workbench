/**
 * @file bsp_adc.h
 * @brief ADC 直接采集、阈值触发采集和双路同步采集的板级接口。
 */
#ifndef BSP_ADC_H
#define BSP_ADC_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** LP-MSPM0G3507 板级层向上提供的逻辑 ADC 通道。 */
typedef enum {
    /* ADC0 通道 0，映射到 PA27。 */
    BSP_ADC_CHANNEL_INPUT_0 = 0,
    /* ADC1 通道 6，映射到 PB19。 */
    BSP_ADC_CHANNEL_INPUT_1,
    BSP_ADC_CHANNEL_COUNT
} BSP_ADC_Channel_e;

typedef struct BSPADCInstance BSPADCInstance;

/** 一次性 DMA 采集完成回调；在 DMA 中断上下文执行。 */
typedef void (*BSPADCDirectCaptureCallback_t)(
    uint32_t sequence, void *context);

/** ADC12 窗口比较器触发采集的异步事件；均在中断上下文执行。 */
typedef enum {
    BSP_ADC_THRESHOLD_CAPTURE_COMPLETE = 0,
    BSP_ADC_THRESHOLD_SIGNAL_REARMED
} BSPADCThresholdEvent_e;

/** ADC12 窗口比较器触发采集事件回调；在 ADC/DMA ISR 中执行。 */
typedef void (*BSPADCThresholdCaptureCallback_t)(
    BSPADCThresholdEvent_e event, uint32_t sequence, void *context);

/** 两路 ADC 配对采集完成回调；在第二路 DMA 中断上下文执行。 */
typedef void (*BSPADCSynchronizedCaptureCallback_t)(
    uint32_t sequence, void *context);

/** 注册指定板级 ADC 通道；只建立硬件映射，不启动采样。 */
BSPADCInstance *BSPADCRegister(BSP_ADC_Channel_e channel);

/**
 * 按指定采样率将连续 sample_count 点一次性写入调用方缓冲区。
 * 2 MHz 使用 4 MSPS 原始采集后二分频，因此 buffer_capacity
 * 至少应为 sample_count * 2；其他当前支持的采样率至少为 sample_count。
 */
bool BSPADCStartDirectCapture(BSPADCInstance *instance,
    uint16_t *buffer, size_t buffer_capacity, size_t sample_count,
    uint32_t sample_rate_hz,
    BSPADCDirectCaptureCallback_t callback, void *context);

/**
 * 启动 PA27 一次性阈值触发采集。
 *
 * 先由 ADC12 窗口比较器监视高阈值；超过阈值后在 ADC ISR 中立即把
 * 当前结果放入 buffer[0]，再启动 DMA 采满剩余采样点。DMA 完成后切换
 * 到低阈值监视，直到信号回落才发出 REARMED 事件并释放 ADC。
 */
bool BSPADCStartThresholdTriggeredCapture(
    BSPADCInstance *instance, uint16_t *buffer, size_t buffer_capacity,
    size_t sample_count, uint32_t sample_rate_hz,
    uint16_t high_threshold_raw, uint16_t low_threshold_raw,
    BSPADCThresholdCaptureCallback_t callback, void *context);

/**
 * 同时启动 PA27/PA21 的一次性配对采集。
 *
 * 当前同步实现使用共享 TIMG0 的定时触发路径（不超过默认 1 MHz）。
 * 两路 DMA 均完成后才调用 callback；两个缓冲区的同一索引属于同一
 * 个采样时刻，可直接用于相位差计算。
 */
bool BSPADCStartSynchronizedCapture(
    BSPADCInstance *first_instance, uint16_t *first_buffer,
    size_t first_buffer_capacity, BSPADCInstance *second_instance,
    uint16_t *second_buffer, size_t second_buffer_capacity,
    size_t sample_count, uint32_t sample_rate_hz,
    BSPADCSynchronizedCaptureCallback_t callback, void *context);

/** 结束或中止当前两路配对采集。 */
bool BSPADCFinishSynchronizedCapture(void);

/** 返回当前是否有两路配对采集正在执行。 */
bool BSPADCIsSynchronizedCaptureActive(void);

/** 结束已完成的采集或中止进行中的采集；结束后 ADC/DMA/定时器保持停止。 */
bool BSPADCFinishDirectCapture(BSPADCInstance *instance);

/** 中止当前阈值监视、DMA 采集或回落等待。 */
bool BSPADCFinishThresholdTriggeredCapture(BSPADCInstance *instance);

/** 返回当前输入是否正在执行一次性 DMA 采集。 */
bool BSPADCIsDirectCaptureActive(const BSPADCInstance *instance);

/** 返回阈值触发链路是否仍占用该 ADC。 */
bool BSPADCIsThresholdTriggeredCaptureActive(
    const BSPADCInstance *instance);

/** 返回 ADC 满量程原始值，当前 12 位 ADC 为 4095。 */
uint16_t BSPADCGetMaximumRawValue(const BSPADCInstance *instance);

/** 返回当前参考电压，单位为毫伏。 */
uint16_t BSPADCGetReferenceMillivolts(const BSPADCInstance *instance);

/** 返回板级默认采样率，当前为 1 MHz。 */
uint32_t BSPADCGetDefaultSampleRateHz(const BSPADCInstance *instance);

/** 判断定时触发或高速 FIFO 路径是否支持指定采样率。 */
bool BSPADCIsSampleRateSupported(uint32_t sample_rate_hz);

#endif
