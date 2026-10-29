/**
 * @file dds.h
 * @brief 直接数字频率合成（给 DAC 或 PWM 出波形用）：32 位相位累加器 + 256 点波表，固定采样率。纯 C。
 *
 *   inc = round(f · 2^32 / fs)，实际频率 = inc · fs / 2^32（分辨率 fs/2^32），
 *   每个样本取相位高 8 位查表。方波可选“整数半周期”模式：每半周期样本数固定，边沿不抖。
 *
 * Source: LP-MSPM0G3507_freertos_firework@ede35a2 modules/dac/dac_output.c
 *   （MIT，Copyright (c) 2026 阡陌）——相位增量/实际频率的取整公式与方波整数半周期做法直接移植（DACOutputStartWaveformLocked）。
 *   改动：频率改为毫赫兹输入；DMA 双缓冲回填、FreeRTOS 任务去掉——调用方在 DMA 半满/全满中断里调 dds_fill。
 * 版本：DDS_VERSION
 */
#ifndef DDS_H
#define DDS_H

#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"

#define DDS_VERSION "1.0.0"
#define DDS_TABLE_N 256u

typedef enum { DDS_SINE = 0, DDS_SQUARE, DDS_TRIANGLE, DDS_SAW } dds_wave_t;

typedef struct {
    uint32_t fs_hz;      /**< 样本输出速率（定时器触发 DAC 的频率），> 0 */
    uint16_t lo, hi;     /**< 输出码范围（如 12 位 DAC 0..4095），lo < hi */
    bool square_exact;   /**< 方波用整数半周期（频率被量化，但每周期一样） */
} dds_cfg_t;

typedef struct {
    dds_cfg_t c;
    uint16_t table[DDS_TABLE_N];
    dds_wave_t wave;
    uint32_t phase, inc;
    uint32_t half_n, idx;       /**< square_exact 时用 */
    uint32_t actual_mhz;
} dds_t;

dz_err_t dds_init(dds_t *d, const dds_cfg_t *c);
/** 设波形与频率（毫赫兹）、起始相位（度）。频率 0 或 > fs/2 返回 DZ_EINVAL，原输出不变。 */
dz_err_t dds_set(dds_t *d, dds_wave_t w, uint32_t freq_mhz, float phase_deg);
/** 实际输出频率（毫赫兹）。 */
uint32_t dds_actual_mhz(const dds_t *d);
uint16_t dds_next(dds_t *d);
void     dds_fill(dds_t *d, uint16_t *buf, uint32_t n);

dz_err_t dds_selftest(void);

#endif /* DDS_H */
