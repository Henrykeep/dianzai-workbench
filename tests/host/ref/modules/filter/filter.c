/* Vendored verbatim (test-only reference) from LP-MSPM0G3507_freertos_firework@ede35a2 modules/filter/filter.c
 * MIT License, Copyright (c) 2026 阡陌 — see firmware/drivers/ad983x/LICENSE-firework.txt. Used by test_sigmods.c to
 * prove firmware/algo/sigfilt (our port) is output-identical. Not linked into firmware. */
/* Filter Module 提供无动态内存的三点中值滤波和一维卡尔曼滤波静态实例。 */
#include "modules/filter/filter.h"

#include <float.h>
#include <stddef.h>

#define FILTER_MEDIAN3_INSTANCE_COUNT (4U)
#define FILTER_KALMAN1D_INSTANCE_COUNT (4U)

struct FilterMedian3Instance {
    /* 最近两个历史采样；新采样由 Process 参数传入。 */
    int32_t older_sample;
    int32_t newer_sample;
    /* false 表示下一次输入需要初始化整个三点窗口。 */
    bool initialized;
    /* 防止使用尚未从静态实例池注册的对象。 */
    bool registered;
};

struct FilterKalman1DInstance {
    FilterKalman1DConfig config;
    float estimate;
    float error_covariance;
    bool estimate_available;
    bool registered;
};

/* 固定实例池可同时服务两路 ADC、UART 波形等多个数据源。 */
static FilterMedian3Instance
    filter_median3_instances[FILTER_MEDIAN3_INSTANCE_COUNT];

/* 卡尔曼实例与中值滤波实例使用彼此独立的静态池。 */
static FilterKalman1DInstance
    filter_kalman1d_instances[FILTER_KALMAN1D_INSTANCE_COUNT];

static bool FilterMedian3IsValid(const FilterMedian3Instance *instance);
static bool FilterKalman1DIsValid(
    const FilterKalman1DInstance *instance);
static bool FilterKalman1DConfigIsValid(
    const FilterKalman1DConfig *config);
static bool FilterValueIsFinite(float value);
static void FilterKalman1DClearState(FilterKalman1DInstance *instance);

/* 通过有限次比较交换取得三个输入中的中间值。 */
int32_t FilterMedian3Calculate(
    int32_t first, int32_t second, int32_t third)
{
    int32_t temporary;

    if (first > second) {
        temporary = first;
        first     = second;
        second    = temporary;
    }
    if (second > third) {
        temporary = second;
        second    = third;
        third     = temporary;
    }
    if (first > second) {
        second = first;
    }

    return second;
}

/* 从固定静态池中分配一个独立的三点中值滤波状态。 */
FilterMedian3Instance *FilterMedian3Register(void)
{
    size_t index;

    for (index = 0U; index < FILTER_MEDIAN3_INSTANCE_COUNT; ++index) {
        FilterMedian3Instance *instance =
            &filter_median3_instances[index];

        if (!instance->registered) {
            instance->older_sample = 0;
            instance->newer_sample = 0;
            instance->initialized  = false;
            instance->registered   = true;
            return instance;
        }
    }

    return NULL;
}

/* 清除已有历史，让下一点成为新的窗口初始值。 */
bool FilterMedian3Reset(FilterMedian3Instance *instance)
{
    if (!FilterMedian3IsValid(instance)) {
        return false;
    }

    instance->older_sample = 0;
    instance->newer_sample = 0;
    instance->initialized  = false;
    return true;
}

/* 将新样本加入长度为三的滑动窗口并输出中值。 */
bool FilterMedian3Process(
    FilterMedian3Instance *instance, int32_t sample, int32_t *filtered)
{
    if (!FilterMedian3IsValid(instance) || (filtered == NULL)) {
        return false;
    }

    if (!instance->initialized) {
        instance->older_sample = sample;
        instance->newer_sample = sample;
        instance->initialized  = true;
        *filtered              = sample;
        return true;
    }

    *filtered = FilterMedian3Calculate(
        instance->older_sample, instance->newer_sample, sample);
    instance->older_sample = instance->newer_sample;
    instance->newer_sample = sample;
    return true;
}

/* 检查三点中值滤波实例是否来自本模块的注册流程。 */
static bool FilterMedian3IsValid(const FilterMedian3Instance *instance)
{
    return (instance != NULL) && instance->registered;
}

/* 从固定静态池注册一维卡尔曼滤波器。 */
FilterKalman1DInstance *FilterKalman1DRegister(
    const FilterKalman1DConfig *config)
{
    size_t index;

    if (!FilterKalman1DConfigIsValid(config)) {
        return NULL;
    }

    for (index = 0U; index < FILTER_KALMAN1D_INSTANCE_COUNT; ++index) {
        FilterKalman1DInstance *instance =
            &filter_kalman1d_instances[index];

        if (!instance->registered) {
            instance->config     = *config;
            instance->registered = true;
            FilterKalman1DClearState(instance);
            return instance;
        }
    }

    return NULL;
}

/* 更新噪声参数，并清除旧参数对应的估计历史。 */
bool FilterKalman1DConfigure(FilterKalman1DInstance *instance,
    const FilterKalman1DConfig *config)
{
    if (!FilterKalman1DIsValid(instance) ||
        !FilterKalman1DConfigIsValid(config)) {
        return false;
    }

    instance->config = *config;
    FilterKalman1DClearState(instance);
    return true;
}

/* 清空估计状态，让下一次测量重新建立初值。 */
bool FilterKalman1DReset(FilterKalman1DInstance *instance)
{
    if (!FilterKalman1DIsValid(instance)) {
        return false;
    }

    FilterKalman1DClearState(instance);
    return true;
}

/* 执行一维卡尔曼的预测步骤和测量更新步骤。 */
bool FilterKalman1DProcess(FilterKalman1DInstance *instance,
    float measurement, float *filtered)
{
    float predicted_covariance;
    float innovation_covariance;
    float kalman_gain;
    float estimate;
    float error_covariance;

    if (!FilterKalman1DIsValid(instance) || (filtered == NULL) ||
        !FilterValueIsFinite(measurement)) {
        return false;
    }

    if (!instance->estimate_available) {
        instance->estimate = measurement;
        instance->error_covariance =
            instance->config.initial_error_covariance;
        instance->estimate_available = true;
        *filtered = measurement;
        return true;
    }

    /* 预测：状态不变，估计误差按过程噪声增加。 */
    predicted_covariance = instance->error_covariance +
                           instance->config.process_noise;
    innovation_covariance = predicted_covariance +
                            instance->config.measurement_noise;
    if (!FilterValueIsFinite(predicted_covariance) ||
        !FilterValueIsFinite(innovation_covariance) ||
        (innovation_covariance <= 0.0F)) {
        return false;
    }

    /* 更新：按卡尔曼增益融合预测值和本次测量值。 */
    kalman_gain = predicted_covariance / innovation_covariance;
    estimate = instance->estimate +
               (kalman_gain * (measurement - instance->estimate));
    error_covariance = (1.0F - kalman_gain) * predicted_covariance;
    if (!FilterValueIsFinite(kalman_gain) ||
        !FilterValueIsFinite(estimate) ||
        !FilterValueIsFinite(error_covariance)) {
        return false;
    }

    /* 浮点舍入可能产生极小负数，协方差物理意义上不能小于 0。 */
    if (error_covariance < 0.0F) {
        error_covariance = 0.0F;
    }

    instance->estimate         = estimate;
    instance->error_covariance = error_covariance;
    *filtered                  = estimate;
    return true;
}

/* 返回最近一次成功更新后保存的状态估计。 */
bool FilterKalman1DGetEstimate(
    const FilterKalman1DInstance *instance, float *estimate)
{
    if (!FilterKalman1DIsValid(instance) || (estimate == NULL) ||
        !instance->estimate_available) {
        return false;
    }

    *estimate = instance->estimate;
    return true;
}

/* 检查卡尔曼实例是否已注册且其配置仍然有效。 */
static bool FilterKalman1DIsValid(
    const FilterKalman1DInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           FilterKalman1DConfigIsValid(&instance->config);
}

/* Q 允许为 0，R 和初始误差协方差必须为正数。 */
static bool FilterKalman1DConfigIsValid(
    const FilterKalman1DConfig *config)
{
    return (config != NULL) &&
           FilterValueIsFinite(config->process_noise) &&
           FilterValueIsFinite(config->measurement_noise) &&
           FilterValueIsFinite(config->initial_error_covariance) &&
           (config->process_noise >= 0.0F) &&
           (config->measurement_noise > 0.0F) &&
           (config->initial_error_covariance > 0.0F);
}

/* 不依赖 libm 检查 NaN 和正负无穷。 */
static bool FilterValueIsFinite(float value)
{
    return (value == value) && (value <= FLT_MAX) &&
           (value >= -FLT_MAX);
}

/* 清空运行状态，配置和注册标志保持不变。 */
static void FilterKalman1DClearState(FilterKalman1DInstance *instance)
{
    instance->estimate           = 0.0F;
    instance->error_covariance   =
        instance->config.initial_error_covariance;
    instance->estimate_available = false;
}
