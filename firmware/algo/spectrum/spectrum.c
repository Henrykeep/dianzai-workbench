/**
 * @file spectrum.c
 * @brief 见 spectrum.h。
 * Source: LP-MSPM0G3507_freertos_firework@ede35a2 modules/fft/fft.c （MIT，Copyright (c) 2026 阡陌）
 */
#include "spectrum.h"
#include <math.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static bool pow2_ok(uint16_t n, uint16_t lo) { return n >= lo && n <= SPEC_MAX_N && (n & (n - 1u)) == 0u; }

dz_err_t spec_fft(float *re, float *im, uint16_t n)
{
    if (!re || !im || !pow2_ok(n, 2u)) return DZ_EINVAL;
    for (uint16_t i = 1, j = 0; i < n; i++) {           /* 位反转 */
        uint16_t bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) { float t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
    }
    for (uint16_t len = 2; len <= n; len <<= 1) {        /* 每级只算一次 sin/cos，旋转因子递推 */
        double ang = -2.0 * M_PI / len;
        float wr0 = (float)cos(ang), wi0 = (float)sin(ang);
        for (uint16_t s = 0; s < n; s += len) {
            float wr = 1.0f, wi = 0.0f;
            for (uint16_t k = 0; k < len / 2u; k++) {
                uint16_t a = s + k, b = a + len / 2u;
                float tr = re[b] * wr - im[b] * wi, ti = re[b] * wi + im[b] * wr;
                re[b] = re[a] - tr; im[b] = im[a] - ti;
                re[a] += tr; im[a] += ti;
                float nwr = wr * wr0 - wi * wi0;
                wi = wr * wi0 + wi * wr0; wr = nwr;
            }
        }
    }
    return DZ_OK;
}

/* 原版 FFTInterpolatePeakOffsetQ16：三点抛物线，限 ±0.5 bin，边界保持整数 bin */
static float interp(const float *m, uint16_t k, uint16_t half)
{
    if (k == 0u || k >= half) return 0.0f;
    float l = m[k - 1u], c = m[k], r = m[k + 1u], curv = l - 2.0f * c + r;
    if (c <= 0.0f || curv >= 0.0f) return 0.0f;
    float off = 0.5f * (l - r) / curv;
    return off > 0.5f ? 0.5f : (off < -0.5f ? -0.5f : off);
}

dz_err_t spec_analyze(spec_work_t *w, const float *x, uint16_t n, float fs_hz,
                      spec_window_t win, bool remove_dc, spec_result_t *r)
{
    if (!w || !x || !r || !pow2_ok(n, SPEC_MIN_N) || !(fs_hz > 0.0f) || !isfinite(fs_hz)) return DZ_EINVAL;
    double mean = 0.0;
    for (uint16_t i = 0; i < n; i++) { if (!isfinite(x[i])) return DZ_EINVAL; mean += (double)x[i]; }
    mean /= n;
    memset(r, 0, sizeof *r);
    r->n = n; r->fs_hz = fs_hz; r->dc = remove_dc ? (float)mean : 0.0f;
    float gain = 0.0f;
    for (uint16_t i = 0; i < n; i++) {
        float v = x[i] - r->dc, wv = 1.0f;
        if (win == SPEC_WIN_HANN) wv = 0.5f * (1.0f - cosf(2.0f * (float)M_PI * (float)i / (float)(n - 1u)));
        gain += wv;
        w->re[i] = v * wv; w->im[i] = 0.0f;
    }
    spec_fft(w->re, w->im, n);
    uint16_t half = n / 2u;
    /* 主峰复数先存（下一步幅值会覆盖工作区）；跳过直流 */
    float best = 0.0f;
    for (uint16_t k = 1; k <= half; k++) {
        float m2 = w->re[k] * w->re[k] + w->im[k] * w->im[k];
        if (m2 > best) { best = m2; r->peak_bin = k; r->peak_re = w->re[k]; r->peak_im = w->im[k]; }
    }
    /* 单边峰值幅度：|X|·2/Σw（直流与奈奎斯特不乘 2） */
    for (uint16_t k = 0; k <= half; k++) {
        float m = sqrtf(w->re[k] * w->re[k] + w->im[k] * w->im[k]) / gain;
        w->re[k] = (k == 0u || k == half) ? m : 2.0f * m;
    }
    const float *mag = w->re;
    if (best <= 0.0f) r->peak_bin = 0;
    r->peak_mag = r->peak_bin ? mag[r->peak_bin] : 0.0f;
    float df = fs_hz / n;
    r->peak_hz = r->peak_bin ? ((float)r->peak_bin + interp(mag, r->peak_bin, half)) * df : 0.0f;
    r->bands[0] = mag[0];
    for (uint16_t b = 1; b < SPEC_BANDS; b++) {           /* 原版：1..N/2 按最大值压成 32 段 */
        uint16_t s = (uint16_t)(((b - 1u) * half) / (SPEC_BANDS - 1u) + 1u), e = (uint16_t)((b * half) / (SPEC_BANDS - 1u));
        if (e < s) e = s;
        float mx = 0.0f;
        for (uint16_t k = s; k <= e; k++) if (mag[k] > mx) mx = mag[k];
        r->bands[b] = mx;
    }
    if (r->peak_mag <= 0.0f) return DZ_OK;
    float thr = r->peak_mag / 20.0f;                      /* 原版：低于主峰 5% 的旁瓣/噪声不算 */
    for (uint16_t k = 1; k <= half; k++) {
        float m = mag[k], l = k > 1u ? mag[k - 1u] : 0.0f, rr = k < half ? mag[k + 1u] : 0.0f;
        if (m < thr || m <= l || m < rr) continue;
        spec_comp_t c = { ((float)k + interp(mag, k, half)) * df, m, k };
        if (r->ncomp < SPEC_COMP_MAX) r->comp[r->ncomp++] = c;
        else {
            uint8_t wk = 0;
            for (uint8_t i = 1; i < SPEC_COMP_MAX; i++) if (r->comp[i].mag < r->comp[wk].mag) wk = i;
            if (c.mag > r->comp[wk].mag) r->comp[wk] = c;
        }
    }
    for (uint8_t i = 1; i < r->ncomp; i++) {              /* 按频率升序（插入排序） */
        spec_comp_t c = r->comp[i]; uint8_t d = i;
        while (d > 0u && r->comp[d - 1u].freq_hz > c.freq_hz) { r->comp[d] = r->comp[d - 1u]; d--; }
        r->comp[d] = c;
    }
    return DZ_OK;
}

float spec_phase_diff_deg(const spec_result_t *a, const spec_result_t *b)
{
    if (!a || !b || !a->peak_bin || a->peak_bin != b->peak_bin || a->n != b->n) return NAN;
    float d = (atan2f(b->peak_im, b->peak_re) - atan2f(a->peak_im, a->peak_re)) * (float)(180.0 / M_PI);
    while (d > 180.0f) d -= 360.0f;
    while (d <= -180.0f) d += 360.0f;
    return d;
}

static float near_max(const float *m, int32_t k, int32_t half)
{
    float mx = 0.0f;
    for (int32_t i = k - 1; i <= k + 1; i++) if (i >= 1 && i <= half && m[i] > mx) mx = m[i];
    return mx;
}

float spec_thd(const spec_work_t *w, const spec_result_t *r, uint8_t harmonics)
{
    if (!w || !r || !r->peak_bin || harmonics < 2u) return NAN;
    int32_t half = r->n / 2;
    float f1 = r->peak_hz * r->n / r->fs_hz, a1 = near_max(w->re, r->peak_bin, half), s = 0.0f;
    if (!(a1 > 0.0f)) return NAN;
    for (uint8_t h = 2; h <= harmonics; h++) {
        int32_t k = (int32_t)lroundf(f1 * h);
        if (k + 1 > half) break;
        float a = near_max(w->re, k, half);
        s += a * a;
    }
    return sqrtf(s) / a1;
}

dz_err_t spectrum_selftest(void)
{
    static spec_work_t w;
    static float x[256];
    spec_result_t r;
    for (int i = 0; i < 256; i++) x[i] = 1.0f + 0.8f * (float)sin(2.0 * M_PI * 1000.0 * i / 25600.0);  /* 正好第 10 bin */
    if (spec_analyze(&w, x, 256, 25600.0f, SPEC_WIN_RECT, true, &r) != DZ_OK) return DZ_EFAIL;
    if (r.peak_bin != 10u || fabsf(r.peak_hz - 1000.0f) > 1.0f || fabsf(r.peak_mag - 0.8f) > 0.01f || fabsf(r.dc - 1.0f) > 1e-3f) return DZ_EFAIL;
    return DZ_OK;
}
