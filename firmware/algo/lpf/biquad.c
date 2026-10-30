#include "biquad.h"
#include <math.h>

/* 净室实现，推导：
 * 双线性变换 s = (1/K)(1 − z⁻¹)/(1 + z⁻¹)，预畸变 K = tan(π fc/fs)（让模拟截止频率映射到数字 fc）。
 * 低通 H(s) = 1/(s² + √2 s + 1)，代入后通分、按 a0 = 1 + √2K + K² 归一：
 *   b0 = K²/a0, b1 = 2b0, b2 = b0, a1 = 2(K² − 1)/a0, a2 = (1 − √2K + K²)/a0。
 * 陷波 H(s) = (s² + gβs + 1)/(s² + βs + 1)，β = 1/Q（ω0 归一），K = tan(ω/2)，α = sin ω/(2Q) 形式：
 *   b0 = (1 + gα)/(1 + α), b1 = −2cos ω/(1 + α), b2 = (1 − gα)/(1 + α), a1 = b1, a2 = (1 − α)/(1 + α)。
 * 直流增益都是 1。实现：直接 II 型转置（数值好、两个状态）。 */

static bool finite_f(float x) { return (x == x) && (x - x == 0.0f); }
#define BQ_PI 3.14159265358979f

static void set(biquad_t *f, float b0, float b1, float b2, float a1, float a2)
{
    f->b0 = b0; f->b1 = b1; f->b2 = b2; f->a1 = a1; f->a2 = a2;
    biquad_clear(f);
}

dz_err_t lpf2p_init(biquad_t *f, float fc, float fs)
{
    if (!f || !finite_f(fc) || !finite_f(fs) || fc <= 0.0f || fs <= 0.0f) return DZ_EINVAL;
    if (fc > 0.4f * fs) fc = 0.4f * fs;
    const float K = tanf(BQ_PI * fc / fs), K2 = K * K, r2 = 1.41421356f;
    const float a0 = 1.0f + r2 * K + K2;
    const float b0 = K2 / a0;
    set(f, b0, 2.0f * b0, b0, 2.0f * (K2 - 1.0f) / a0, (1.0f - r2 * K + K2) / a0);
    return DZ_OK;
}

dz_err_t notch_init(biquad_t *f, float fc, float bw, float att_db, float fs)
{
    if (!f || !finite_f(fc) || !finite_f(bw) || !finite_f(att_db) || !finite_f(fs)) return DZ_EINVAL;
    if (fc <= 0.0f || bw <= 0.0f || att_db <= 0.0f || fs <= 0.0f || fc >= 0.5f * fs || bw >= 2.0f * fc) return DZ_EINVAL;
    const float g = powf(10.0f, -att_db / 20.0f);        /* 中心处剩余增益 */
    const float Q = fc / bw;
    const float w = 2.0f * BQ_PI * fc / fs, alpha = sinf(w) / (2.0f * Q), inv = 1.0f / (1.0f + alpha);
    const float b1 = -2.0f * cosf(w) * inv;
    set(f, (1.0f + g * alpha) * inv, b1, (1.0f - g * alpha) * inv, b1, (1.0f - alpha) * inv);
    return DZ_OK;
}

void biquad_reset(biquad_t *f, float x0)
{
    if (!f || !finite_f(x0)) return;
    /* DF2T 稳态（输入恒为 x0、输出 y = x0，直流增益 1）：
     * y = b0·x0 + s1 → s1 = x0(1 − b0)；s2 = b2·x0 − a2·y = x0(b2 − a2)。 */
    f->d1 = x0 * (1.0f - f->b0);
    f->d2 = x0 * (f->b2 - f->a2);
    f->y = x0;
    f->primed = true;
}

void biquad_clear(biquad_t *f)
{
    if (!f) return;
    f->d1 = 0.0f; f->d2 = 0.0f; f->primed = false;
}

float biquad_update(biquad_t *f, float x)
{
    if (!f) return 0.0f;
    if (!finite_f(x)) return f->y;                      /* 坏样本丢弃，状态不被污染 */
    if (!f->primed) biquad_reset(f, x);
    const float y = f->b0 * x + f->d1;
    f->d1 = f->b1 * x - f->a1 * y + f->d2;
    f->d2 = f->b2 * x - f->a2 * y;
    f->y = y;
    return y;
}

static bool close_to(float a, float b, float tol) { float d = a - b; return d < tol && d > -tol; }

/* 正弦稳态增益：跑 40 个周期，取后半段峰值 */
static float sine_gain(biquad_t *f, float hz, float fs)
{
    float peak = 0.0f;
    const int n = (int)(fs / hz * 40.0f);
    biquad_reset(f, 0.0f);
    for (int i = 0; i < n; i++) {
        const float y = biquad_update(f, sinf(2.0f * BQ_PI * hz * (float)i / fs));
        if (i > n / 2 && fabsf(y) > peak) peak = fabsf(y);
    }
    return peak;
}

dz_err_t biquad_selftest(void)
{
    biquad_t f;
    if (lpf2p_init(&f, 0.0f, 1000.0f) != DZ_EINVAL) return DZ_EFAIL;
    if (notch_init(&f, 50.0f, 200.0f, 40.0f, 1000.0f) != DZ_EINVAL) return DZ_EFAIL;
    if (lpf2p_init(&f, 32.7f, 1000.0f) != DZ_OK) return DZ_EFAIL;
    if (!close_to(biquad_update(&f, 5.0f), 5.0f, 1e-4f)) return DZ_EFAIL;       /* 首样本预置 */
    if (!close_to(biquad_update(&f, NAN), 5.0f, 1e-4f)) return DZ_EFAIL;       /* NaN 丢弃 */
    if (!close_to(sine_gain(&f, 100.0f, 1000.0f), 0.1f, 0.01f)) return DZ_EFAIL;/* −20 dB */
    if (!close_to(sine_gain(&f, 2.0f, 1000.0f), 1.0f, 0.01f)) return DZ_EFAIL;
    if (notch_init(&f, 50.0f, 20.0f, 40.0f, 1000.0f) != DZ_OK) return DZ_EFAIL;
    if (sine_gain(&f, 50.0f, 1000.0f) > 0.02f) return DZ_EFAIL;                 /* 中心 −40 dB */
    if (!close_to(sine_gain(&f, 5.0f, 1000.0f), 1.0f, 0.02f)) return DZ_EFAIL;
    return DZ_OK;
}
