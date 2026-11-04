/*
 * FFT Module 封装 CMSIS-DSP Q15 实数 FFT，并完成定标、幅值计算和频率分量提取。
 */
#include "modules/fft/fft.h"

#include "application/app_config.h"

#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U

#include <stddef.h>

#include "FreeRTOS.h"
#include "semphr.h"

#include "arm_const_structs.h"
#include "arm_math.h"

#define FFT_Q15_MAXIMUM (32767)
#define FFT_Q15_MINIMUM (-32768)
/* 忽略低于主峰 5% 的泄漏旁瓣和噪声局部峰。 */
#define FFT_COMPONENT_MINIMUM_MAGNITUDE_DIVISOR (20U)

struct FFTInstance {
    FFTConfig config;
    q15_t complex_buffer[FFT_MAX_POINT_COUNT * 2U];
    bool registered;
};

static FFTInstance fft_instance;
static SemaphoreHandle_t fft_mutex;
static StaticSemaphore_t fft_mutex_control;

static bool FFTIsValid(const FFTInstance *instance);
static bool FFTConfigIsValid(const FFTConfig *config);
static q15_t FFTSaturateQ15(int32_t value);
static const arm_cfft_instance_q15 *FFTGetCFFTInstance(
    size_t point_count);
static q15_t FFTGetHannWindowValue(
    size_t index, size_t point_count);
static void FFTPrepareComplexInput(
    FFTInstance *instance, const int16_t *samples,
    size_t point_count);
static void FFTPrepareUnsignedComplexInput(
    FFTInstance *instance, const uint16_t *samples,
    size_t point_count, uint16_t midscale,
    uint8_t left_shift);
static void FFTConvertComplexToMagnitudes(
    FFTInstance *instance, size_t positive_bin_count);
static void FFTCapturePeakComplex(
    const FFTInstance *instance, size_t positive_bin_count,
    FFTResult *result);
static uint16_t FFTGetMagnitude(
    const FFTInstance *instance, size_t bin);
static void FFTCopySpectrumResult(
    FFTInstance *instance, size_t point_count,
    uint32_t sample_rate_hz,
    FFTResult *result);
static uint32_t FFTCalculateFrequencyMillihz(
    const FFTInstance *instance, size_t peak_bin,
    size_t positive_bin_count, size_t point_count,
    uint32_t sample_rate_hz);
static void FFTExtractComponents(
    const FFTInstance *instance, size_t positive_bin_count,
    size_t point_count, uint32_t sample_rate_hz,
    FFTResult *result);
static int32_t FFTInterpolatePeakOffsetQ16(
    const FFTInstance *instance, size_t peak_bin,
    size_t positive_bin_count);

FFTInstance *FFTRegister(const FFTConfig *config)
{
    if (!FFTConfigIsValid(config)) {
        return NULL;
    }

    if (fft_instance.registered) {
        return &fft_instance;
    }

    if (fft_mutex == NULL) {
        fft_mutex = xSemaphoreCreateMutexStatic(&fft_mutex_control);
        if (fft_mutex == NULL) {
            return NULL;
        }
    }

    fft_instance.config     = *config;
    fft_instance.registered = true;
    return &fft_instance;
}

/* CMSIS-DSP CFFT 使用复数交错缓冲区，实数输入的虚部统一填 0。 */
bool FFTAnalyzeQ15(FFTInstance *instance, const int16_t *samples,
    size_t sample_count, FFTResult *result)
{
    return FFTAnalyzeQ15AtSampleRate(instance, samples,
        sample_count, FFTGetSampleRateHz(instance), result);
}

/* 使用调用方提供的采样率计算频率坐标，FFT 幅度处理保持不变。 */
bool FFTAnalyzeQ15AtSampleRate(FFTInstance *instance,
    const int16_t *samples, size_t sample_count,
    uint32_t sample_rate_hz, FFTResult *result)
{
    const arm_cfft_instance_q15 *cfft_instance;

    if (!FFTIsValid(instance) || (samples == NULL) ||
        !FFTPointCountIsSupported(sample_count) ||
        (sample_rate_hz == 0UL) || (result == NULL) ||
        (xSemaphoreTake(fft_mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    cfft_instance = FFTGetCFFTInstance(sample_count);
    if (cfft_instance == NULL) {
        (void)xSemaphoreGive(fft_mutex);
        return false;
    }
    FFTPrepareComplexInput(instance, samples, sample_count);
    arm_cfft_q15(cfft_instance, instance->complex_buffer,
        0U, 1U);
    FFTCapturePeakComplex(instance, sample_count / 2U, result);
    FFTConvertComplexToMagnitudes(instance, sample_count / 2U);
    FFTCopySpectrumResult(instance, sample_count,
        sample_rate_hz, result);

    (void)xSemaphoreGive(fft_mutex);
    return true;
}

bool FFTAnalyzeUnsignedAtSampleRate(FFTInstance *instance,
    const uint16_t *samples, size_t sample_count,
    uint16_t midscale, uint8_t left_shift,
    uint32_t sample_rate_hz, FFTResult *result)
{
    const arm_cfft_instance_q15 *cfft_instance;

    if (!FFTIsValid(instance) || (samples == NULL) ||
        !FFTPointCountIsSupported(sample_count) ||
        (left_shift > 15U) || (sample_rate_hz == 0UL) ||
        (result == NULL) ||
        (xSemaphoreTake(fft_mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }
    cfft_instance = FFTGetCFFTInstance(sample_count);
    if (cfft_instance == NULL) {
        (void)xSemaphoreGive(fft_mutex);
        return false;
    }
    FFTPrepareUnsignedComplexInput(instance, samples,
        sample_count, midscale, left_shift);
    arm_cfft_q15(cfft_instance, instance->complex_buffer,
        0U, 1U);
    FFTCapturePeakComplex(instance, sample_count / 2U, result);
    FFTConvertComplexToMagnitudes(instance, sample_count / 2U);
    FFTCopySpectrumResult(instance, sample_count,
        sample_rate_hz, result);
    (void)xSemaphoreGive(fft_mutex);
    return true;
}

uint16_t *FFTGetUnsignedCaptureBuffer(
    FFTInstance *instance, size_t sample_count)
{
    if (!FFTIsValid(instance) ||
        !FFTPointCountIsSupported(sample_count)) {
        return NULL;
    }
    return (uint16_t *)(void *)instance->complex_buffer;
}

uint32_t FFTGetSampleRateHz(const FFTInstance *instance)
{
    return FFTIsValid(instance)
               ? instance->config.sample_rate_hz
               : 0UL;
}

size_t FFTGetPointCount(const FFTInstance *instance)
{
    return FFTIsValid(instance) ? FFT_MAX_POINT_COUNT : 0U;
}

bool FFTPointCountIsSupported(size_t point_count)
{
    return (point_count >= FFT_MIN_POINT_COUNT) &&
           (point_count <= FFT_MAX_POINT_COUNT) &&
           ((point_count & (point_count - 1U)) == 0U);
}

static bool FFTIsValid(const FFTInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           FFTConfigIsValid(&instance->config) && (fft_mutex != NULL);
}

static bool FFTConfigIsValid(const FFTConfig *config)
{
    return (config != NULL) && (config->sample_rate_hz > 0UL) &&
           (config->window >= FFT_WINDOW_RECTANGULAR) &&
           (config->window < FFT_WINDOW_COUNT);
}

static q15_t FFTSaturateQ15(int32_t value)
{
    if (value > FFT_Q15_MAXIMUM) {
        return (q15_t)FFT_Q15_MAXIMUM;
    }
    if (value < FFT_Q15_MINIMUM) {
        return (q15_t)FFT_Q15_MINIMUM;
    }
    return (q15_t)value;
}

static const arm_cfft_instance_q15 *FFTGetCFFTInstance(
    size_t point_count)
{
    switch (point_count) {
        case 64U:
            return &arm_cfft_sR_q15_len64;
        case 128U:
            return &arm_cfft_sR_q15_len128;
        case 256U:
            return &arm_cfft_sR_q15_len256;
        case 512U:
            return &arm_cfft_sR_q15_len512;
        case 1024U:
            return &arm_cfft_sR_q15_len1024;
        case 2048U:
            return &arm_cfft_sR_q15_len2048;
        default:
            return NULL;
    }
}

/* arm_cos_q15 的 0～0x7fff 对应 0～2pi。 */
static q15_t FFTGetHannWindowValue(
    size_t index, size_t point_count)
{
    uint32_t phase;
    int32_t cosine;

    if ((point_count < 2U) || (index >= point_count)) {
        return 0;
    }
    if ((index == 0U) || (index == (point_count - 1U))) {
        return 0;
    }
    phase = (uint32_t)(((uint64_t)index * 32768ULL) /
        (point_count - 1U));
    cosine = arm_cos_q15((q15_t)(uint16_t)phase);
    return (q15_t)((32767 - cosine) / 2);
}

/* 可选去直流后应用窗函数，并写入 CMSIS-DSP 复数输入缓冲区。 */
static void FFTPrepareComplexInput(
    FFTInstance *instance, const int16_t *samples,
    size_t point_count)
{
    int32_t mean = 0;
    size_t index;

    if (instance->config.remove_dc) {
        for (index = 0U; index < point_count; ++index) {
            mean += samples[index];
        }
        mean /= (int32_t)point_count;
    }

    for (index = 0U; index < point_count; ++index) {
        int32_t value = (int32_t)samples[index] - mean;

        if (instance->config.window == FFT_WINDOW_HANN) {
            value = (value *
                FFTGetHannWindowValue(index, point_count) +
                16384) >> 15U;
        }

        instance->complex_buffer[index * 2U] = FFTSaturateQ15(value);
        instance->complex_buffer[(index * 2U) + 1U] = 0;
    }
}

static void FFTPrepareUnsignedComplexInput(
    FFTInstance *instance, const uint16_t *samples,
    size_t point_count, uint16_t midscale,
    uint8_t left_shift)
{
    int32_t mean = 0;
    size_t index;

    if (instance->config.remove_dc) {
        for (index = 0U; index < point_count; ++index) {
            mean += samples[index];
        }
        mean /= (int32_t)point_count;
    } else {
        mean = midscale;
    }

    /*
     * DMA 输入可以与 complex_buffer 共用起始地址。此时必须从后向前展开，
     * 否则写入虚部会覆盖下一项尚未读取的 uint16_t 原始样本。
     */
    index = point_count;
    while (index > 0U) {
        int32_t value;

        --index;
        value = ((int32_t)samples[index] - mean) *
            (int32_t)(1UL << left_shift);

        if (instance->config.window == FFT_WINDOW_HANN) {
            value = (value *
                FFTGetHannWindowValue(index, point_count) +
                16384) >> 15U;
        }
        instance->complex_buffer[index * 2U] =
            FFTSaturateQ15(value);
        instance->complex_buffer[(index * 2U) + 1U] = 0;
    }
}

/*
 * 复数结果转换为单边幅值后直接写回工作区前半段。读取位置每次前进两个
 * q15_t，写入位置只前进一个，因此不会覆盖后续尚未处理的复数值。
 */
static void FFTConvertComplexToMagnitudes(
    FFTInstance *instance, size_t positive_bin_count)
{
    size_t bin;

    for (bin = 0U; bin <= positive_bin_count; ++bin) {
        int32_t real = instance->complex_buffer[bin * 2U];
        int32_t imaginary =
            instance->complex_buffer[(bin * 2U) + 1U];
        uint32_t magnitude_squared = (uint32_t)(
            ((int64_t)real * real) +
            ((int64_t)imaginary * imaginary));
        q31_t magnitude_q31 = 0;

        (void)arm_sqrt_q31(magnitude_squared >> 1U, &magnitude_q31);
        instance->complex_buffer[bin] =
            (q15_t)(magnitude_q31 >> 16U);
    }
}

/*
 * 幅值转换会覆盖复数工作区，因此提前保存最强交流 bin 的实部和虚部。
 * 两路同步采样使用相同窗函数和点数时，可由这两个复数向量直接求相位差。
 */
static void FFTCapturePeakComplex(
    const FFTInstance *instance, size_t positive_bin_count,
    FFTResult *result)
{
    uint32_t maximum_magnitude_squared = 0UL;
    size_t bin;

    result->peak_bin = 0U;
    result->peak_real = 0;
    result->peak_imaginary = 0;
    for (bin = 1U; bin <= positive_bin_count; ++bin) {
        int32_t real = instance->complex_buffer[bin * 2U];
        int32_t imaginary =
            instance->complex_buffer[(bin * 2U) + 1U];
        uint32_t magnitude_squared = (uint32_t)(
            ((int64_t)real * real) +
            ((int64_t)imaginary * imaginary));

        if (magnitude_squared > maximum_magnitude_squared) {
            maximum_magnitude_squared = magnitude_squared;
            result->peak_bin = (uint16_t)bin;
            result->peak_real = (int16_t)real;
            result->peak_imaginary = (int16_t)imaginary;
        }
    }
}

static uint16_t FFTGetMagnitude(
    const FFTInstance *instance, size_t bin)
{
    q15_t magnitude;

    if ((instance == NULL) ||
        (bin > (FFT_MAX_POINT_COUNT / 2U))) {
        return 0U;
    }
    magnitude = instance->complex_buffer[bin];
    return (magnitude > 0) ? (uint16_t)magnitude : 0U;
}

/* 只保留实数输入的不重复半谱，并跳过直流寻找主峰。 */
static void FFTCopySpectrumResult(
    FFTInstance *instance, size_t point_count,
    uint32_t sample_rate_hz,
    FFTResult *result)
{
    size_t positive_bin_count = point_count / 2U;
    size_t bin;

    result->peak_magnitude = (result->peak_bin > 0U)
                                 ? FFTGetMagnitude(
                                       instance, result->peak_bin)
                                 : 0U;
    result->point_count    = (uint16_t)point_count;
    result->magnitudes[0] = FFTGetMagnitude(instance, 0U);

    /* 将任意点数的 1～N/2 bin 按最大值压缩为 32 个显示频带。 */
    for (bin = 1U; bin < FFT_BIN_COUNT; ++bin) {
        size_t source_start =
            (((bin - 1U) * positive_bin_count) /
                (FFT_BIN_COUNT - 1U)) + 1U;
        size_t source_end =
            ((bin * positive_bin_count) /
                (FFT_BIN_COUNT - 1U));
        uint16_t maximum = 0U;
        size_t source_bin;

        if (source_end < source_start) {
            source_end = source_start;
        }
        for (source_bin = source_start;
             source_bin <= source_end; ++source_bin) {
            uint16_t magnitude =
                FFTGetMagnitude(instance, source_bin);
            if (magnitude > maximum) {
                maximum = magnitude;
            }
        }
        result->magnitudes[bin] = maximum;
    }

    result->peak_frequency_millihz =
        FFTCalculateFrequencyMillihz(instance, result->peak_bin,
            positive_bin_count, point_count, sample_rate_hz);
    FFTExtractComponents(instance, positive_bin_count,
        point_count, sample_rate_hz, result);
}

/* 按指定局部峰执行与主峰相同的三点插值和频率换算。 */
static uint32_t FFTCalculateFrequencyMillihz(
    const FFTInstance *instance, size_t peak_bin,
    size_t positive_bin_count, size_t point_count,
    uint32_t sample_rate_hz)
{
    int64_t peak_bin_q16;
    uint64_t frequency_numerator;
    uint64_t frequency_denominator;

    if ((instance == NULL) || (peak_bin == 0U) ||
        (peak_bin > positive_bin_count) || (point_count == 0U) ||
        (sample_rate_hz == 0UL)) {
        return 0UL;
    }
    peak_bin_q16 = ((int64_t)peak_bin << 16U) +
        FFTInterpolatePeakOffsetQ16(instance,
            peak_bin, positive_bin_count);
    frequency_numerator = (uint64_t)peak_bin_q16 *
        sample_rate_hz * 1000ULL;
    frequency_denominator = (uint64_t)point_count << 16U;
    return (uint32_t)(
        (frequency_numerator + (frequency_denominator / 2ULL)) /
        frequency_denominator);
}

/* 保留最强的有效局部峰，最后按频率升序排列供小屏分页显示。 */
static void FFTExtractComponents(
    const FFTInstance *instance, size_t positive_bin_count,
    size_t point_count, uint32_t sample_rate_hz,
    FFTResult *result)
{
    uint16_t minimum_magnitude;
    size_t bin;
    size_t index;

    if ((instance == NULL) || (result == NULL)) {
        return;
    }
    result->component_count = 0U;
    if (result->peak_magnitude == 0U) {
        return;
    }
    minimum_magnitude = (uint16_t)(
        ((uint32_t)result->peak_magnitude +
            (FFT_COMPONENT_MINIMUM_MAGNITUDE_DIVISOR - 1U)) /
        FFT_COMPONENT_MINIMUM_MAGNITUDE_DIVISOR);

    for (bin = 1U; bin <= positive_bin_count; ++bin) {
        uint16_t magnitude = FFTGetMagnitude(instance, bin);
        uint16_t left = (bin > 1U)
                            ? FFTGetMagnitude(instance, bin - 1U)
                            : 0U;
        uint16_t right = (bin < positive_bin_count)
                             ? FFTGetMagnitude(instance, bin + 1U)
                             : 0U;
        FFTComponent component;

        if ((magnitude < minimum_magnitude) ||
            (magnitude <= left) || (magnitude < right)) {
            continue;
        }
        component.frequency_millihz =
            FFTCalculateFrequencyMillihz(instance, bin,
                positive_bin_count, point_count, sample_rate_hz);
        component.magnitude = magnitude;
        component.bin = (uint16_t)bin;

        if (result->component_count < FFT_COMPONENT_MAX_COUNT) {
            result->components[result->component_count] = component;
            ++result->component_count;
        } else {
            size_t weakest_index = 0U;

            for (index = 1U; index < FFT_COMPONENT_MAX_COUNT; ++index) {
                if (result->components[index].magnitude <
                    result->components[weakest_index].magnitude) {
                    weakest_index = index;
                }
            }
            if (component.magnitude >
                result->components[weakest_index].magnitude) {
                result->components[weakest_index] = component;
            }
        }
    }

    for (index = 1U; index < result->component_count; ++index) {
        FFTComponent component = result->components[index];
        size_t destination = index;

        while ((destination > 0U) &&
               (result->components[destination - 1U].frequency_millihz >
                   component.frequency_millihz)) {
            result->components[destination] =
                result->components[destination - 1U];
            --destination;
        }
        result->components[destination] = component;
    }
}

/*
 * 使用主峰左、中、右三个幅值做抛物线插值。
 * 返回 Q16 bin 偏移，并限制在 -0.5～+0.5 bin；DC 和 Nyquist
 * 边界没有完整邻点，保持整数 bin。
 */
static int32_t FFTInterpolatePeakOffsetQ16(
    const FFTInstance *instance, size_t peak_bin,
    size_t positive_bin_count)
{
    int32_t left;
    int32_t center;
    int32_t right;
    int32_t curvature;
    int64_t offset_q16;

    if ((instance == NULL) || (peak_bin == 0U) ||
        (peak_bin >= positive_bin_count)) {
        return 0;
    }

    left = FFTGetMagnitude(instance, peak_bin - 1U);
    center = FFTGetMagnitude(instance, peak_bin);
    right = FFTGetMagnitude(instance, peak_bin + 1U);
    curvature = left - (2 * center) + right;
    if ((center == 0) || (curvature >= 0)) {
        return 0;
    }

    offset_q16 = ((int64_t)(left - right) * 32768LL) /
        curvature;
    if (offset_q16 > 32768LL) {
        offset_q16 = 32768LL;
    } else if (offset_q16 < -32768LL) {
        offset_q16 = -32768LL;
    }
    return (int32_t)offset_q16;
}

#endif /* APP_ENABLE_WAVEFORM_MEASUREMENT */
