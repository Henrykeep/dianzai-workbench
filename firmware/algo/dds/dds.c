/**
 * @file dds.c
 * @brief 见 dds.h。
 * Source: LP-MSPM0G3507_freertos_firework@ede35a2 modules/dac/dac_output.c （MIT，Copyright (c) 2026 阡陌）
 */
#include "dds.h"
#include <math.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

dz_err_t dds_init(dds_t *d, const dds_cfg_t *c)
{
    if (!d || !c || c->fs_hz == 0u || c->lo >= c->hi) return DZ_EINVAL;
    memset(d, 0, sizeof *d);
    d->c = *c;
    for (uint32_t i = 0; i < DDS_TABLE_N; i++) d->table[i] = c->lo;
    return DZ_OK;
}

static void build(dds_t *d)
{
    float lo = d->c.lo, span = (float)(d->c.hi - d->c.lo);
    for (uint32_t i = 0; i < DDS_TABLE_N; i++) {
        float u = (float)i / DDS_TABLE_N, v;               /* 0..1 一个周期 */
        switch (d->wave) {
        case DDS_SINE:     v = 0.5f + 0.5f * sinf(2.0f * (float)M_PI * u); break;
        case DDS_SQUARE:   v = u < 0.5f ? 1.0f : 0.0f; break;
        case DDS_TRIANGLE: v = u < 0.5f ? 2.0f * u : 2.0f - 2.0f * u; break;
        default:           v = u; break;
        }
        d->table[i] = (uint16_t)lroundf(lo + v * span);
    }
}

dz_err_t dds_set(dds_t *d, dds_wave_t w, uint32_t f_mhz, float phase_deg)
{
    if (!d || w > DDS_SAW || f_mhz == 0u || (uint64_t)f_mhz * 2u > (uint64_t)d->c.fs_hz * 1000u || !isfinite(phase_deg)) return DZ_EINVAL;
    uint64_t fs_m = (uint64_t)d->c.fs_hz * 1000u;
    uint64_t inc = (((uint64_t)f_mhz << 32) + fs_m / 2u) / fs_m;     /* 原版取整公式 */
    if (inc == 0u || inc > UINT32_MAX) return DZ_EINVAL;
    d->wave = w; d->inc = (uint32_t)inc;
    float ph = fmodf(phase_deg, 360.0f); if (ph < 0.0f) ph += 360.0f;
    d->phase = (uint32_t)((double)ph / 360.0 * 4294967296.0);
    build(d);
    if (w == DDS_SQUARE && d->c.square_exact) {
        uint64_t two_f = (uint64_t)f_mhz * 2u;
        d->half_n = (uint32_t)((fs_m + two_f / 2u) / two_f);            /* 原版：(fs + f) / (2f) */
        if (d->half_n == 0u) d->half_n = 1u;
        d->idx = (uint32_t)((double)ph / 360.0 * 2.0 * d->half_n);
        d->actual_mhz = (uint32_t)((fs_m + d->half_n) / (2u * d->half_n));
    } else {
        d->half_n = 0;
        d->actual_mhz = (uint32_t)(((uint64_t)d->inc * fs_m + (1ull << 31)) >> 32);
    }
    return DZ_OK;
}

uint32_t dds_actual_mhz(const dds_t *d) { return d ? d->actual_mhz : 0u; }

uint16_t dds_next(dds_t *d)
{
    if (!d) return 0;
    if (d->half_n) {
        uint16_t v = d->idx < d->half_n ? d->c.hi : d->c.lo;
        if (++d->idx >= 2u * d->half_n) d->idx = 0;
        return v;
    }
    uint16_t v = d->table[d->phase >> 24];
    d->phase += d->inc;
    return v;
}

void dds_fill(dds_t *d, uint16_t *buf, uint32_t n)
{
    if (!d || !buf) return;
    for (uint32_t i = 0; i < n; i++) buf[i] = dds_next(d);
}

dz_err_t dds_selftest(void)
{
    dds_t d; dds_cfg_t c = { 100000u, 0, 4095, false };
    if (dds_init(&d, &c) || dds_set(&d, DDS_SINE, 1000000u, 0.0f)) return DZ_EFAIL;
    if (dds_actual_mhz(&d) < 999999u || dds_actual_mhz(&d) > 1000001u) return DZ_EFAIL;
    return dds_set(&d, DDS_SINE, 60000000u, 0.0f) == DZ_EINVAL ? DZ_OK : DZ_EFAIL;   /* 超奈奎斯特 */
}
