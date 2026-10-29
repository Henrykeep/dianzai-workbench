/**
 * @file spectrum.h
 * @brief 实数采样的频谱分析：去直流、Hann 窗、基 2 FFT、单边幅值、主峰三点插值、局部峰分量表、
 *        32 段显示频带、同批双通道相位差、THD。纯 C（float），无硬件依赖。
 *
 * Source: LP-MSPM0G3507_freertos_firework@ede35a2 modules/fft/fft.c
 *   （MIT，Copyright (c) 2026 阡陌）——分析流程直接移植：主峰跳过直流、抛物线插值限 ±0.5 bin、
 *   分量门限 = 主峰/20、保留最强 16 个后按频率排序、按最大值压成 32 段、保存主峰复数供相位差。
 *   改动：q15 + CMSIS-DSP arm_cfft_q15 → float + 自写基 2 FFT（主机可测；板上要快可换 CMSIS-DSP，接口不变）；
 *   幅值换算成“单边峰值幅度”（正弦幅度 A → peak_mag≈A，Hann 已补相干增益）；去掉 FreeRTOS 互斥量
 *   （工作区由调用方提供，一个工作区不要两个任务同时用）；新增 THD。
 *
 * 版本：SPECTRUM_VERSION
 */
#ifndef SPECTRUM_H
#define SPECTRUM_H

#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"

#define SPECTRUM_VERSION "1.0.0"

#define SPEC_MIN_N     64u
#define SPEC_MAX_N     1024u   /**< 工作区 2×4×N 字节：1024 点 = 8 KB。MSPM0G3507 只有 32 KB RAM，按需改小 */
#define SPEC_BANDS     33u     /**< [0] = 直流，[1..32] = 显示频带 */
#define SPEC_COMP_MAX  16u

typedef enum { SPEC_WIN_RECT = 0, SPEC_WIN_HANN = 1 } spec_window_t;

typedef struct { float freq_hz; float mag; uint16_t bin; } spec_comp_t;

typedef struct {
    uint16_t n;
    float fs_hz;
    float dc;                    /**< 去直流前的均值（remove_dc=false 时为 0） */
    uint16_t peak_bin;           /**< 0 = 没有交流分量 */
    float peak_hz, peak_mag;
    float peak_re, peak_im;      /**< 主峰复数（相位差用） */
    float bands[SPEC_BANDS];
    spec_comp_t comp[SPEC_COMP_MAX];
    uint8_t ncomp;
} spec_result_t;

/** 工作区。spec_analyze 之后 re[0..n/2] 是单边幅值谱（spec_thd 要用）。 */
typedef struct { float re[SPEC_MAX_N]; float im[SPEC_MAX_N]; } spec_work_t;

/** 原地基 2 复数 FFT（不归一化）。n 须为 2 的幂且 2..SPEC_MAX_N。 */
dz_err_t spec_fft(float *re, float *im, uint16_t n);

/** 分析 n 点实数样本。n 须为 2 的幂、SPEC_MIN_N..SPEC_MAX_N；fs_hz > 0；样本含 NaN 返回 DZ_EINVAL。 */
dz_err_t spec_analyze(spec_work_t *w, const float *x, uint16_t n, float fs_hz,
                      spec_window_t win, bool remove_dc, spec_result_t *r);

/** 同批同步采样的两路（同 n、同窗）主峰相位差 b − a，单位度，(-180, 180]。主峰 bin 不同返回 NAN。 */
float spec_phase_diff_deg(const spec_result_t *a, const spec_result_t *b);

/** 总谐波失真 sqrt(Σ A_k²)/A_1，k = 2..harmonics（超出奈奎斯特的跳过）。每次谐波取理论 bin ±1 的最大值。
 *  须紧接在同一工作区的 spec_analyze 之后调用。无主峰返回 NAN。 */
float spec_thd(const spec_work_t *w, const spec_result_t *r, uint8_t harmonics);

dz_err_t spectrum_selftest(void);

#endif /* SPECTRUM_H */
