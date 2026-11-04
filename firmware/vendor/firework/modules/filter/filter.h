/**
 * @file filter.h
 * @brief 三点中值滤波与一维卡尔曼滤波的注册、复位和处理接口。
 */
#ifndef FILTER_H
#define FILTER_H

#include <stdbool.h>
#include <stdint.h>

/** 三点中值滤波器的不透明实例。 */
typedef struct FilterMedian3Instance FilterMedian3Instance;

/** 一维卡尔曼滤波的噪声和初始误差配置。 */
typedef struct {
    /** 过程噪声 Q；越大越快跟随信号变化。 */
    float process_noise;
    /** 测量噪声 R；越大越不信任新测量值。 */
    float measurement_noise;
    /** 首次测量后使用的初始估计误差协方差。 */
    float initial_error_covariance;
} FilterKalman1DConfig;

/** 一维卡尔曼滤波器的不透明实例。 */
typedef struct FilterKalman1DInstance FilterKalman1DInstance;

/**
 * @brief 直接计算三个有符号整数的中值。
 *
 * 本接口不保存历史状态，可用于已经取得三个采样值的场景。
 */
int32_t FilterMedian3Calculate(
    int32_t first, int32_t second, int32_t third);

/**
 * @brief 注册一个保存最近三个采样值的流式滤波器。
 *
 * 模块使用固定静态实例池，不申请堆内存。实例耗尽时返回 NULL。
 */
FilterMedian3Instance *FilterMedian3Register(void);

/** 清除历史数据；下一次输入会重新初始化整个三点窗口。 */
bool FilterMedian3Reset(FilterMedian3Instance *instance);

/**
 * @brief 输入一个新采样，并返回最近三个采样的中值。
 *
 * 第一个采样会同时填充三个历史位置，因此第一次调用即可得到输出。
 * 每个实例应由同一个任务调用，不能在中断服务函数中使用。
 */
bool FilterMedian3Process(
    FilterMedian3Instance *instance, int32_t sample, int32_t *filtered);

/** 注册一个一维卡尔曼滤波器；配置无效或静态实例耗尽时返回 NULL。 */
FilterKalman1DInstance *FilterKalman1DRegister(
    const FilterKalman1DConfig *config);

/** 应用新的 Q、R 和初始协方差，同时清除已有估计状态。 */
bool FilterKalman1DConfigure(FilterKalman1DInstance *instance,
    const FilterKalman1DConfig *config);

/** 清除估计历史；下一次测量会重新初始化滤波器。 */
bool FilterKalman1DReset(FilterKalman1DInstance *instance);

/**
 * @brief 输入一个新测量值，并返回更新后的一维状态估计。
 *
 * 第一次输入直接作为初始估计，从第二次输入开始执行预测和测量更新。
 * 每个实例应固定由同一个任务调用，不能在中断服务函数中使用。
 */
bool FilterKalman1DProcess(FilterKalman1DInstance *instance,
    float measurement, float *filtered);

/** 返回最近估计值；尚未输入任何测量数据时返回 false。 */
bool FilterKalman1DGetEstimate(
    const FilterKalman1DInstance *instance, float *estimate);

#endif
