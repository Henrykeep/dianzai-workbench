/**
 * @file sigfilt.h
 * @brief 三点中值滤波（去单点毛刺）+ 一维卡尔曼（随机游走模型）。纯 C，无硬件依赖。
 *
 * Source: LP-MSPM0G3507_freertos_firework@ede35a2 modules/filter/filter.c
 *   （MIT，Copyright (c) 2026 阡陌）——算法与边界处理直接移植：中值首点填满窗口、卡尔曼首测量作初值、
 *   协方差舍入成负数时钳到 0、Q≥0 / R>0 / P0>0。改动：静态实例池 → 调用方持有句柄；bool → dz_err_t。
 * 版本：SIGFILT_VERSION
 */
#ifndef SIGFILT_H
#define SIGFILT_H

#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"

#define SIGFILT_VERSION "1.0.0"

typedef struct { int32_t older, newer; bool primed; } med3_t;

int32_t med3_of(int32_t a, int32_t b, int32_t c);
void    med3_reset(med3_t *m);
/** 第一个样本直接输出并填满窗口。m 为 NULL 时原样返回 x。 */
int32_t med3_update(med3_t *m, int32_t x);

typedef struct {
    float q;    /**< 过程噪声：越大跟得越快 */
    float r;    /**< 测量噪声：越大越不信新测量 */
    float p0;   /**< 首次测量后的估计误差协方差 */
} kf1_cfg_t;

typedef struct { kf1_cfg_t c; float x, p; bool primed; } kf1_t;

dz_err_t kf1_init(kf1_t *k, const kf1_cfg_t *c);   /**< 参数非法返回 DZ_EINVAL，句柄不变 */
void     kf1_reset(kf1_t *k);
/** 输入一个测量值，*out 为新估计。测量 NaN/Inf 或数值溢出返回 DZ_EINVAL，状态不变。 */
dz_err_t kf1_update(kf1_t *k, float z, float *out);
/** 稳态卡尔曼增益（等价一阶低通的 alpha），用于和 algo/lpf 对照选参数。 */
float    kf1_steady_gain(const kf1_cfg_t *c);

dz_err_t sigfilt_selftest(void);

#endif /* SIGFILT_H */
