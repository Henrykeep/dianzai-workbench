/**
 * @file biquad.h
 * @brief 二阶低通（Butterworth，双线性）+ 陷波（RBJ cookbook）。纯 C，初始化用 math.h，update 只有乘加。
 *
 * 净室推导（只用公开教材，不参照任何 GPL 实现），推导写在 biquad.c：
 *  - 低通：模拟二阶 Butterworth H(s) = 1/(s² + √2 s + 1)，预畸变双线性变换（Oppenheim & Schafer, Discrete-Time Signal Processing §7.1）。
 *  - 陷波：模拟有限深度陷波 H(s) = (s² + g·(ω0/Q)s + ω0²)/(s² + (ω0/Q)s + ω0²)，g = 10^(−att/20)，Q = fc/bw；
 *    同样双线性变换，系数形式同 R. Bristow-Johnson《Audio EQ Cookbook》的 notch/peaking（W3C 公开版）。
 * 为什么要它：同样在 100 Hz 衰减 20 dB（fs=1 kHz），lpf1 在 2 Hz 滞后 11.1°，lpf2p 只 4.9°（见 README）。
 */
#ifndef BIQUAD_H
#define BIQUAD_H
#include <stdbool.h>
#include "dz_err.h"

typedef struct {
    float b0, b1, b2, a1, a2;
    float d1, d2;          /* 直接 II 型转置状态 */
    float y;               /* 上次输出 */
    bool  primed;
} biquad_t;

/** 二阶 Butterworth 低通。fc 自动夹到 ≤ 0.4·fs（离奈奎斯特留余量，tan 预畸变不发散）。非法参数返回 DZ_EINVAL。 */
dz_err_t lpf2p_init(biquad_t *f, float cutoff_hz, float sample_hz);
/** 陷波：中心 center_hz，带宽 bw_hz（-3 dB 两点间），中心衰减 att_db（>0，如 40）。 */
dz_err_t notch_init(biquad_t *f, float center_hz, float bw_hz, float att_db, float sample_hz);
/** 输入一个样本。首样本按直流稳态预置（不从 0 爬升）；NaN/Inf 丢弃返回上次输出；NULL 返回 0。 */
float biquad_update(biquad_t *f, float x);
/** 预置到稳态输入 x0（直流增益 1 的滤波器输出即 x0）。 */
void  biquad_reset(biquad_t *f, float x0);
/** 下一样本重新预置。 */
void  biquad_clear(biquad_t *f);
dz_err_t biquad_selftest(void);
#endif
