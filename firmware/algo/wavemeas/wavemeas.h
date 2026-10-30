/**
 * @file wavemeas.h
 * @brief 波形参数测量：一块 ADC 原始码 → 最小/最大/峰峰/均值/交流有效值、频率/周期（施密特过零 + 线性插值）、
 *        占空比、波形类型（直流/正弦/方波/三角/锯齿/谐波），以及两路同步采样的相位差（单频 DFT）。纯 C，无硬件依赖。
 *
 * Source: LP-MSPM0G3507_freertos_firework@ede35a2 application/waveform/waveform_measurement/waveform_measurement.c
 *   （MIT，Copyright (c) 2026 阡陌）——时域特征提取 WaveformMeasurementExtractTimeFeatures 与轻量分类
 *   WaveformMeasurementClassifyWaveform 直接移植（全部定点阈值原样保留）；频谱特征改用本仓库 spectrum 的
 *   spec_result_t（32 段压缩频带与原版 FFT_ANALYSIS_BIN_COUNT 同构）。
 *   改动：去掉 FreeRTOS 任务/DMA/COMP 捕获/订阅；原版频率来自硬件捕获或 FFT，这里另加纯样本的施密特过零测频
 *   （板上有 capfreq/FFT 时仍可用它们）；占空比改为只统计整周期内（不足一周期回退原版全窗统计）；
 *   相位差原版用同窗 FFT 主峰复数相乘 + arm_atan2_q31，这里用已知频率的单频 DFT（Hann 窗），频率不必落在 bin 上。
 *
 * 版本：WAVEMEAS_VERSION
 */
#ifndef WAVEMEAS_H
#define WAVEMEAS_H

#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "spectrum.h"

#define WAVEMEAS_VERSION "1.0.0"

#define WM_MIN_P2P_RAW 8u        /**< 原版：峰峰值低于 8 个码视为无信号/直流 */

typedef enum { WM_UNKNOWN = 0, WM_DC, WM_SINE, WM_SQUARE, WM_TRIANGLE, WM_SAWTOOTH, WM_HARMONIC } wm_type_t;

/** 原版 WaveformMeasurementTimeFeatures（逐字段同名含义）。 */
typedef struct {
    uint16_t min_raw, max_raw, avg_raw;
    uint32_t high_count, low_rail_count, high_rail_count;
    uint32_t peak_dev, max_step;
    uint64_t sum_sq, sum_abs_step, sum_sq_step, sum_abs_d2;
} wm_feat_t;

enum { WM_V_LEVEL = 1u << 0, WM_V_FREQ = 1u << 1, WM_V_DUTY = 1u << 2, WM_V_TYPE = 1u << 3 };

typedef struct {
    float min_v, max_v, pp_v, avg_v, rms_ac_v;  /**< 乘过 lsb_v（lsb_v = 0 时为原始码） */
    float freq_hz, period_s;                    /**< 0 = 窗口里不足两个上升沿 */
    float duty;                                 /**< 0..1，高于中点电平的时间比例 */
    uint16_t edges;                             /**< 上升沿个数 */
    wm_type_t type;
    uint8_t valid;                              /**< WM_V_* */
} wm_result_t;

/** 原版时域特征。n ≥ 2。 */
dz_err_t wm_features(const uint16_t *x, uint32_t n, wm_feat_t *f);

/** 原版分类。spec 可为 NULL（只用时域规则：方波/锯齿/正弦/三角按峰值因数）。 */
wm_type_t wm_classify(const wm_feat_t *f, uint32_t n, const spec_result_t *spec);

/**
 * 测量一块样本。fs_hz > 0；lsb_v = 每个码多少伏（例如 3.3/4095，含分压倍数），0 表示直接用码值。
 * spec 可为 NULL（同一块样本的 spec_analyze 结果，给分类用）。
 */
dz_err_t wm_measure(const uint16_t *x, uint32_t n, float fs_hz, float lsb_v,
                    const spec_result_t *spec, wm_result_t *r);

/**
 * 同批同步采样的两路在 freq_hz 处的相位差 b − a（度，(-180, 180]，正 = b 超前）。
 * 先各自去均值、加 Hann 窗再做单频 DFT。freq 无效、任一路幅度太小返回 NAN。
 */
float wm_phase_deg(const uint16_t *a, const uint16_t *b, uint32_t n, float fs_hz, float freq_hz);

dz_err_t wavemeas_selftest(void);

#endif
