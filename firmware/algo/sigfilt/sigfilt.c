/**
 * @file sigfilt.c
 * @brief 见 sigfilt.h。
 * Source: LP-MSPM0G3507_freertos_firework@ede35a2 modules/filter/filter.c （MIT，Copyright (c) 2026 阡陌）
 */
#include "sigfilt.h"
#include <math.h>
#include <string.h>

int32_t med3_of(int32_t a, int32_t b, int32_t c)
{
    int32_t t;
    if (a > b) { t = a; a = b; b = t; }
    if (b > c) { t = b; b = c; c = t; }
    if (a > b) b = a;
    return b;
}

void med3_reset(med3_t *m) { if (m) memset(m, 0, sizeof *m); }

int32_t med3_update(med3_t *m, int32_t x)
{
    if (!m) return x;
    if (!m->primed) { m->older = m->newer = x; m->primed = true; return x; }
    int32_t y = med3_of(m->older, m->newer, x);
    m->older = m->newer; m->newer = x;
    return y;
}

static bool cfg_ok(const kf1_cfg_t *c)
{
    return c && isfinite(c->q) && isfinite(c->r) && isfinite(c->p0) && c->q >= 0.0f && c->r > 0.0f && c->p0 > 0.0f;
}

dz_err_t kf1_init(kf1_t *k, const kf1_cfg_t *c)
{
    if (!k || !cfg_ok(c)) return DZ_EINVAL;
    memset(k, 0, sizeof *k);
    k->c = *c;
    return DZ_OK;
}

void kf1_reset(kf1_t *k) { if (k) { k->primed = false; k->x = 0.0f; k->p = 0.0f; } }

dz_err_t kf1_update(kf1_t *k, float z, float *out)
{
    if (!k || !out || !isfinite(z)) return DZ_EINVAL;
    if (!k->primed) { k->x = z; k->p = k->c.p0; k->primed = true; *out = z; return DZ_OK; }
    float pp = k->p + k->c.q, s = pp + k->c.r;               /* 预测：状态不变，协方差 + Q */
    if (!isfinite(pp) || !isfinite(s) || s <= 0.0f) return DZ_EINVAL;
    float g = pp / s, x = k->x + g * (z - k->x), p = (1.0f - g) * pp;
    if (!isfinite(g) || !isfinite(x) || !isfinite(p)) return DZ_EINVAL;
    if (p < 0.0f) p = 0.0f;                                  /* 舍入成负数时钳到 0 */
    k->x = x; k->p = p; *out = x;
    return DZ_OK;
}

float kf1_steady_gain(const kf1_cfg_t *c)
{
    if (!cfg_ok(c)) return NAN;
    /* 稳态先验 P⁻ 满足 P⁻² − Q·P⁻ − Q·R = 0 */
    float pm = 0.5f * (c->q + sqrtf(c->q * c->q + 4.0f * c->q * c->r));
    return pm / (pm + c->r);
}

dz_err_t sigfilt_selftest(void)
{
    med3_t m = { 0 };
    if (med3_update(&m, 5) != 5 || med3_update(&m, 100) != 5 || med3_update(&m, 6) != 6) return DZ_EFAIL;
    kf1_t k; kf1_cfg_t c = { 0.01f, 1.0f, 1.0f }; float y = 0.0f;
    if (kf1_init(&k, &c) || kf1_update(&k, 2.0f, &y) || y != 2.0f) return DZ_EFAIL;
    return DZ_OK;
}
