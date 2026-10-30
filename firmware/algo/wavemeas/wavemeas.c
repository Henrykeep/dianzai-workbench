/**
 * @file wavemeas.c
 * @brief 见 wavemeas.h。
 * Source: LP-MSPM0G3507_freertos_firework@ede35a2 application/waveform/waveform_measurement/waveform_measurement.c
 *   （MIT，Copyright (c) 2026 阡陌）：wm_features / wm_classify 移植自 ExtractTimeFeatures / ClassifyWaveform。
 */
#include "wavemeas.h"
#include <math.h>
#include <stddef.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* 原版定点阈值（CLASSIFY_SCALE = 10000 表示 1.0） */
#define SCALE              10000ULL
#define RAIL_MARGIN        1000ULL
#define SQUARE_RAIL_MIN    7000UL
#define SQUARE_SIDE_MIN    500UL
#define SQUARE_CREST2_MAX  13500ULL
#define SINE_RAIL_MIN      3000UL
#define SINE_RAIL_CREST2_MAX 27000ULL
#define SPECTRAL_MIN       5500UL
#define SINE_CREST2_MIN    14000ULL
#define SINE_CREST2_MAX    24500ULL
#define TRI_CREST2_MAX     40000ULL
#define TRI_STEP_UNIF_MAX  14000ULL
#define TRI_H3_MIN         500UL
#define TRI_CURV_FACTOR    54000ULL
#define TRI_CURV_MIN_BIN   16u
#define TRI_CURV_MIN_SAMPLES 5u
#define SAW_JUMP_FACTOR    4ULL

static uint32_t uabs(int32_t v) { return v < 0 ? (uint32_t)(-v) : (uint32_t)v; }

dz_err_t wm_features(const uint16_t *x, uint32_t n, wm_feat_t *f)
{
    if (!x || n < 2u || !f) return DZ_EINVAL;
    *f = (wm_feat_t){0};
    f->min_raw = f->max_raw = x[0];
    uint64_t sum = 0;
    for (uint32_t i = 0; i < n; i++) {
        if (x[i] < f->min_raw) f->min_raw = x[i];
        if (x[i] > f->max_raw) f->max_raw = x[i];
        sum += x[i];
    }
    f->avg_raw = (uint16_t)((sum + n / 2u) / n);
    uint32_t pp = (uint32_t)f->max_raw - f->min_raw;
    uint16_t thr = (uint16_t)(f->min_raw + pp / 2u);
    uint32_t lo_lim = f->min_raw + (uint32_t)(((uint64_t)pp * RAIL_MARGIN) / SCALE);
    uint32_t hi_lim = f->max_raw - (uint32_t)(((uint64_t)pp * RAIL_MARGIN) / SCALE);
    int32_t prev_step = 0;
    bool prev_ok = false;
    for (uint32_t i = 0; i < n; i++) {
        uint32_t ad = uabs((int32_t)x[i] - (int32_t)f->avg_raw);
        if (pp >= WM_MIN_P2P_RAW && x[i] >= thr) f->high_count++;
        if (x[i] <= lo_lim) f->low_rail_count++;
        if (x[i] >= hi_lim) f->high_rail_count++;
        if (ad > f->peak_dev) f->peak_dev = ad;
        f->sum_sq += (uint64_t)ad * ad;
        if (i > 0u) {
            int32_t step = (int32_t)x[i] - (int32_t)x[i - 1u];
            uint32_t as = uabs(step);
            if (prev_ok) f->sum_abs_d2 += uabs(step - prev_step);
            prev_step = step;
            prev_ok = true;
            f->sum_abs_step += as;
            f->sum_sq_step += (uint64_t)as * as;
            if (as > f->max_step) f->max_step = as;
        }
    }
    return DZ_OK;
}

wm_type_t wm_classify(const wm_feat_t *f, uint32_t n, const spec_result_t *s)
{
    if (!f || n < 2u || f->max_raw < f->min_raw) return WM_UNKNOWN;
    uint32_t pp = (uint32_t)f->max_raw - f->min_raw;
    if (pp < WM_MIN_P2P_RAW || f->sum_sq == 0u || f->peak_dev == 0u) return WM_DC;
    uint64_t crest2 = (((uint64_t)f->peak_dev * f->peak_dev * n * SCALE) + f->sum_sq / 2u) / f->sum_sq;
    uint32_t lo_r = (uint32_t)(((uint64_t)f->low_rail_count * SCALE) / n);
    uint32_t hi_r = (uint32_t)(((uint64_t)f->high_rail_count * SCALE) / n);
    uint32_t tot_r = lo_r + hi_r;
    if (crest2 <= SQUARE_CREST2_MAX && tot_r >= SQUARE_RAIL_MIN && lo_r >= SQUARE_SIDE_MIN && hi_r >= SQUARE_SIDE_MIN)
        return WM_SQUARE;
    if (crest2 > SINE_CREST2_MAX && crest2 <= TRI_CREST2_MAX && f->sum_abs_step > 0u &&
        (uint64_t)f->max_step * (n - 1u) > f->sum_abs_step * SAW_JUMP_FACTOR)
        return WM_SAWTOOTH;

    uint64_t unif = UINT64_MAX;
    uint32_t curv = UINT32_MAX, curv_lim = 0, dom = 0, h3 = 0;
    if (f->sum_abs_step > 0u) {
        uint64_t s2 = f->sum_abs_step * f->sum_abs_step;
        unif = (f->sum_sq_step * (n - 1u) * SCALE + s2 / 2u) / s2;
        curv = (uint32_t)((f->sum_abs_d2 * SCALE + f->sum_abs_step / 2u) / f->sum_abs_step);
    }
    if (s && s->n >= 2u && s->peak_bin > 0u && s->peak_mag > 0.0f) {
        float sum = 0.0f;
        for (unsigned b = 1; b < SPEC_BANDS; b++) sum += s->bands[b];
        if (sum > 0.0f) dom = (uint32_t)(s->peak_mag * (float)SCALE / sum + 0.5f);
        uint32_t N = s->n, half = N / 2u;
        if (s->peak_bin >= TRI_CURV_MIN_BIN && s->peak_bin <= (N + TRI_CURV_MIN_SAMPLES - 1u) / TRI_CURV_MIN_SAMPLES)
            curv_lim = (uint32_t)((TRI_CURV_FACTOR * s->peak_bin + N / 2u) / N);
        uint32_t k3 = ((uint32_t)s->peak_bin * 3u) % N;
        if (k3 > half) k3 = N - k3;                          /* 原版：超奈奎斯特按混叠频率找 */
        if (half > 0u && k3 > 0u && k3 <= half) {
            uint32_t fb = (uint32_t)(((uint64_t)s->peak_bin * (SPEC_BANDS - 1u) + (half - 1u)) / half);
            uint32_t cb = (uint32_t)(((uint64_t)k3 * (SPEC_BANDS - 1u) + (half - 1u)) / half);
            if (cb > 0u && cb < SPEC_BANDS && cb != fb) h3 = (uint32_t)(s->bands[cb] * (float)SCALE / s->peak_mag + 0.5f);
        }
    }
    if (h3 >= TRI_H3_MIN && unif <= TRI_STEP_UNIF_MAX) return WM_TRIANGLE;
    if (curv_lim > 0u && crest2 > SQUARE_CREST2_MAX && curv <= curv_lim) return WM_TRIANGLE;
    if (s && s->peak_bin > 0u && dom < SPECTRAL_MIN) return WM_HARMONIC;
    if (crest2 > SQUARE_CREST2_MAX && crest2 <= SINE_RAIL_CREST2_MAX && tot_r >= SINE_RAIL_MIN &&
        lo_r >= SQUARE_SIDE_MIN && hi_r >= SQUARE_SIDE_MIN)
        return WM_SINE;
    if (crest2 >= SINE_CREST2_MIN && crest2 <= SINE_CREST2_MAX) return WM_SINE;
    if (crest2 <= TRI_CREST2_MAX) return WM_TRIANGLE;
    return WM_HARMONIC;
}

dz_err_t wm_measure(const uint16_t *x, uint32_t n, float fs_hz, float lsb_v, const spec_result_t *spec, wm_result_t *r)
{
    if (!r || !(fs_hz > 0.0f) || !(lsb_v >= 0.0f)) return DZ_EINVAL;
    wm_feat_t f;
    dz_err_t e = wm_features(x, n, &f);
    if (e != DZ_OK) return e;
    float k = lsb_v > 0.0f ? lsb_v : 1.0f;
    *r = (wm_result_t){0};
    r->min_v = f.min_raw * k;
    r->max_v = f.max_raw * k;
    r->pp_v = r->max_v - r->min_v;
    float mean = 0.0f;
    for (uint32_t i = 0; i < n; i++) mean += x[i];
    mean /= (float)n;
    r->avg_v = mean * k;
    double ss = 0.0;
    for (uint32_t i = 0; i < n; i++) { double d = (double)x[i] - (double)mean; ss += d * d; }
    r->rms_ac_v = (float)sqrt(ss / n) * k;
    r->valid = WM_V_LEVEL;
    r->type = wm_classify(&f, n, spec);
    if (r->type != WM_UNKNOWN) r->valid |= WM_V_TYPE;
    uint32_t pp = (uint32_t)f.max_raw - f.min_raw;
    if (pp < WM_MIN_P2P_RAW) return DZ_OK;

    /* 施密特过零：中点 ± 10% 峰峰，上升沿在穿过中点处线性插值 */
    float mid = f.min_raw + pp / 2.0f, hy = pp * 0.1f;
    bool high = x[0] > mid;
    float first = -1.0f, last = -1.0f;
    uint32_t i_first = 0, i_last = 0;
    for (uint32_t i = 1; i < n; i++) {
        if (!high && x[i] >= mid + hy) {
            high = true;
            uint32_t j = i;                                   /* 往回找穿过中点的那一步 */
            while (j > 0u && x[j - 1u] >= mid) j--;
            float t = (float)j;
            if (j > 0u && x[j] != x[j - 1u]) t = (float)(j - 1u) + (mid - x[j - 1u]) / (float)(x[j] - x[j - 1u]);
            if (first < 0.0f) { first = t; i_first = j; }
            last = t; i_last = j;
            r->edges++;
        } else if (high && x[i] <= mid - hy) {
            high = false;
        }
    }
    if (r->edges >= 2u && last > first) {
        r->period_s = (last - first) / (float)(r->edges - 1u) / fs_hz;
        r->freq_hz = 1.0f / r->period_s;
        r->valid |= WM_V_FREQ;
        uint32_t hc = 0;                                      /* 整周期内的占空比 */
        for (uint32_t i = i_first; i < i_last; i++) if (x[i] >= mid) hc++;
        r->duty = (float)hc / (float)(i_last - i_first);
    } else {
        r->duty = (float)f.high_count / (float)n;             /* 原版：全窗中点统计 */
    }
    r->valid |= WM_V_DUTY;
    return DZ_OK;
}

static void dft1(const uint16_t *x, uint32_t n, double w, double *re, double *im)
{
    double mean = 0.0;
    for (uint32_t i = 0; i < n; i++) mean += x[i];
    mean /= n;
    *re = *im = 0.0;
    for (uint32_t i = 0; i < n; i++) {
        double win = 0.5 - 0.5 * cos(2.0 * M_PI * (double)i / (double)(n - 1u));
        double v = (x[i] - mean) * win;
        *re += v * cos(w * (double)i);
        *im -= v * sin(w * (double)i);
    }
}

float wm_phase_deg(const uint16_t *a, const uint16_t *b, uint32_t n, float fs_hz, float freq_hz)
{
    if (!a || !b || n < 8u || !(fs_hz > 0.0f) || !(freq_hz > 0.0f) || freq_hz >= fs_hz / 2.0f) return NAN;
    double w = 2.0 * M_PI * (double)freq_hz / (double)fs_hz;
    double ar, ai, br, bi;
    dft1(a, n, w, &ar, &ai);
    dft1(b, n, w, &br, &bi);
    if (ar * ar + ai * ai < 1e-6 || br * br + bi * bi < 1e-6) return NAN;
    double rr = br * ar + bi * ai, ri = bi * ar - br * ai;   /* B · conj(A)，与原版相同 */
    float d = (float)(atan2(ri, rr) * 180.0 / M_PI);
    return d <= -180.0f ? d + 360.0f : d;
}

dz_err_t wavemeas_selftest(void)
{
    static uint16_t s[256];
    for (unsigned i = 0; i < 256; i++) s[i] = (uint16_t)(2048 + 1000 * sin(2 * M_PI * 8.0 * i / 256));
    wm_result_t r;
    if (wm_measure(s, 256, 256.0f, 0.0f, NULL, &r) != DZ_OK) return DZ_EIO;
    if (!(r.valid & WM_V_FREQ) || fabsf(r.freq_hz - 8.0f) > 0.1f || r.type != WM_SINE) return DZ_EIO;
    return DZ_OK;
}
