/**
 * @file fft_analysis.h
 * @brief PA27/PB19/UART2/UART3 多输入 FFT 结果快照和外部频谱接口。
 */
#ifndef FFT_ANALYSIS_H
#define FFT_ANALYSIS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "modules/fft/fft.h"

#define FFT_ANALYSIS_UART2_POINT_COUNT (64U)
#define FFT_ANALYSIS_MAX_POINT_COUNT (2048U)
/* 复数 FFT 工作区可在分析前暂存的 uint16_t 原始点数。 */
#define FFT_ANALYSIS_ADC_CAPTURE_BUFFER_CAPACITY \
    (FFT_ANALYSIS_MAX_POINT_COUNT * 2U)
#define FFT_ANALYSIS_BIN_COUNT (33U)
#define FFT_ANALYSIS_UART2_SAMPLE_RATE_HZ (100U)

/** FFT Analysis Module 可分析的输入数据源。 */
typedef enum {
    FFT_ANALYSIS_INPUT_PA27 = 0,
    FFT_ANALYSIS_INPUT_PB19,
    /* 兼容旧调用名：当前硬件实际为 PB19 / ADC1.6。 */
    FFT_ANALYSIS_INPUT_PA21 = FFT_ANALYSIS_INPUT_PB19,
    FFT_ANALYSIS_INPUT_UART2,
    FFT_ANALYSIS_INPUT_UART3,
    FFT_ANALYSIS_INPUT_COUNT
} FFTAnalysisInput_e;

/** 指定 ADC 输入最新一帧的单边频谱。 */
typedef struct {
    uint16_t magnitudes[FFT_ANALYSIS_BIN_COUNT];
    FFTComponent components[FFT_COMPONENT_MAX_COUNT];
    uint16_t peak_magnitude;
    uint16_t peak_bin;
    /** 主峰复数结果，供同步双通道相位测量使用。 */
    int16_t peak_real;
    int16_t peak_imaginary;
    uint32_t peak_frequency_millihz;
    uint32_t sample_rate_hz;
    uint32_t source_sequence;
    uint32_t sequence;
    uint16_t point_count;
    uint8_t component_count;
    FFTAnalysisInput_e input;
} FFTAnalysisResult;

/** FFT 结果发布观察者；在发起本次分析的任务上下文执行。 */
typedef void (*FFTAnalysisResultReadyCallback_t)(
    FFTAnalysisInput_e input, uint32_t source_sequence,
    void *context);

/** 初始化 FFT 工作区；启用 UART2 时同时创建异步帧分析任务。 */
bool FFTAnalysisInit(void);

/** 复制指定输入最近完成的频谱。 */
bool FFTAnalysisCopyLatestResult(FFTAnalysisInput_e input,
    FFTAnalysisResult *result);

/**
 * 发布外部控制器已经计算好的非负频谱。
 * magnitudes 为从 0 Hz 到 maximum_frequency_hz 等间隔排列的原始频谱点；
 * 本函数会最大值保持压缩到 33 个 OLED 频带。外部分量的 magnitude 单位由
 * 数据源约定，UART3 当前使用整数 mV。
 */
bool FFTAnalysisPublishExternalSpectrum(FFTAnalysisInput_e input,
    const uint32_t *magnitudes, size_t magnitude_count,
    const FFTComponent *components, size_t component_count,
    uint32_t maximum_frequency_hz, uint32_t source_sequence);

/** 对测量应用累计的 ADC 原始样本执行自定义点数 FFT 并发布。 */
bool FFTAnalysisAnalyzeADCSamples(FFTAnalysisInput_e input,
    const uint16_t *samples, size_t sample_count,
    uint32_t sample_rate_hz, uint32_t source_sequence);

/**
 * 独占 FFT 工作区并把它作为 ADC DMA 缓冲区返回；忙碌或参数非法时返回
 * NULL。返回区域的原始样本容量为
 * FFT_ANALYSIS_ADC_CAPTURE_BUFFER_CAPACITY。成功后必须调用
 * FFTAnalysisAnalyzeCapturedADCSamples() 或 FFTAnalysisReleaseADCCaptureBuffer()
 * 释放工作区。
 */
uint16_t *FFTAnalysisAcquireADCCaptureBuffer(size_t sample_count);

/** 分析工作区中刚采集完成的 ADC 数据，并在返回前释放工作区。 */
bool FFTAnalysisAnalyzeCapturedADCSamples(FFTAnalysisInput_e input,
    size_t sample_count, uint32_t sample_rate_hz,
    uint32_t source_sequence);

/** 中止尚未进入分析的 ADC 采集并释放 FFT 工作区。 */
void FFTAnalysisReleaseADCCaptureBuffer(void);

/** 向 UART2 FFT 输入提交一个有符号采样；UART2 关闭时返回 false。 */
bool FFTAnalysisSubmitUART2Sample(int16_t sample);

/** 注册一个 FFT 结果就绪观察者。 */
bool FFTAnalysisSubscribeResultReady(
    FFTAnalysisResultReadyCallback_t callback, void *context);

/**
 * 移除先前注册的 FFT 结果观察者。
 * @warning 返回后，已由 FFT 任务取得快照的回调仍可能再执行一次；context 必须
 * 保持有效，直到调用方确认该次发布已经结束。
 */
bool FFTAnalysisUnsubscribeResultReady(
    FFTAnalysisResultReadyCallback_t callback, void *context);

/** 返回 FFT Analysis 工作区是否已经初始化。 */
bool FFTAnalysisIsRunning(void);

#endif
