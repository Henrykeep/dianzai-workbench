/**
 * @file fft.h
 * @brief Q15 实数 FFT、幅值频谱和主要频率分量分析接口。
 */
#ifndef FFT_H
#define FFT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** CMSIS-DSP Q15 CFFT 当前允许的最大点数。 */
#define FFT_MAX_POINT_COUNT (2048U)
#define FFT_MIN_POINT_COUNT (64U)

/** 公开结果保留 DC + 32 个压缩频带，便于 OLED 统一显示。 */
#define FFT_BIN_COUNT (33U)
/** 一帧最多保留的有效局部峰数量。 */
#define FFT_COMPONENT_MAX_COUNT (16U)

/** 从完整正频率半谱中提取的一个有效频率分量。 */
typedef struct {
    uint32_t frequency_millihz;
    uint16_t magnitude;
    uint16_t bin;
} FFTComponent;

/** FFT 输入窗函数。 */
typedef enum {
    FFT_WINDOW_RECTANGULAR = 0,
    FFT_WINDOW_HANN,
    FFT_WINDOW_COUNT
} FFT_Window_e;

/** FFT 实例配置。 */
typedef struct {
    uint32_t sample_rate_hz;
    FFT_Window_e window;
    bool remove_dc;
} FFTConfig;

/** 一帧实数输入的单边频谱结果。 */
typedef struct {
    uint16_t magnitudes[FFT_BIN_COUNT];
    FFTComponent components[FFT_COMPONENT_MAX_COUNT];
    uint16_t peak_magnitude;
    uint16_t peak_bin;
    /** 主峰 bin 的复数 FFT 结果；用于同批双通道相位差计算。 */
    int16_t peak_real;
    int16_t peak_imaginary;
    uint32_t peak_frequency_millihz;
    uint16_t point_count;
    uint8_t component_count;
} FFTResult;

/** FFT 模块不透明实例。 */
typedef struct FFTInstance FFTInstance;

/** 注册可分析 64～2048 点 Q15 FFT 的实例。 */
FFTInstance *FFTRegister(const FFTConfig *config);

/**
 * 对 64/128/256/512/1024/2048 个 Q15 实数样本执行 FFT。
 */
bool FFTAnalyzeQ15(FFTInstance *instance, const int16_t *samples,
    size_t sample_count, FFTResult *result);

/** 使用指定采样率分析一帧数据，适合 UART 等外部采样源。 */
bool FFTAnalyzeQ15AtSampleRate(FFTInstance *instance,
    const int16_t *samples, size_t sample_count,
    uint32_t sample_rate_hz, FFTResult *result);

/** 将无符号 ADC 样本直接装入 FFT 工作区，避免额外大缓冲区。 */
bool FFTAnalyzeUnsignedAtSampleRate(FFTInstance *instance,
    const uint16_t *samples, size_t sample_count,
    uint16_t midscale, uint8_t left_shift,
    uint32_t sample_rate_hz, FFTResult *result);

/**
 * 返回与复数 FFT 工作区重叠的无符号 ADC DMA 缓冲区。
 * 调用方必须保证 DMA 写入、原始样本处理和 FFT 分时执行。
 */
uint16_t *FFTGetUnsignedCaptureBuffer(
    FFTInstance *instance, size_t sample_count);

/** 返回实例配置的采样频率。 */
uint32_t FFTGetSampleRateHz(const FFTInstance *instance);

/** 返回当前支持的最大 FFT 点数。 */
size_t FFTGetPointCount(const FFTInstance *instance);

/** 判断点数是否为当前支持的 2 的幂。 */
bool FFTPointCountIsSupported(size_t point_count);

#endif
