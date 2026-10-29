/**
 * @file capfreq.c
 * @brief 见 capfreq.h。代码自写。
 */
#include "capfreq.h"
#include <math.h>
#include <string.h>

dz_err_t capfreq_init(capfreq_t *c, const capfreq_cfg_t *cfg)
{
    if (!c || !cfg || cfg->timer_hz == 0u || cfg->periods == 0u || cfg->periods > 32u || cfg->timeout_ms == 0u) return DZ_EINVAL;
    memset(c, 0, sizeof *c);
    c->c = *cfg;
    c->duty = NAN;
    return DZ_OK;
}

void capfreq_reset(capfreq_t *c)
{
    if (!c) return;
    capfreq_cfg_t cfg = c->c; uint32_t seq = c->seq;
    capfreq_init(c, &cfg);
    c->seq = seq;
}

static uint32_t span(const capfreq_t *c, uint32_t a, uint32_t b)
{
    return c->c.wrap ? (uint32_t)(((uint64_t)b + c->c.wrap - a) % c->c.wrap) : b - a;
}

void capfreq_edge(capfreq_t *c, uint32_t tick, bool rising, uint32_t now_ms)
{
    if (!c) return;
    if (c->have_rise && now_ms - c->last_edge_ms > c->c.timeout_ms) capfreq_reset(c);   /* 断过信号，重新起算 */
    c->last_edge_ms = now_ms;
    if (!rising) {
        if (c->have_rise) { c->high_sum += span(c, c->last_rise, tick); c->high_valid = true; }
        return;
    }
    if (!c->have_rise) { c->have_rise = true; c->last_rise = tick; c->period_sum = 0; c->high_sum = 0; c->high_valid = false; return; }
    c->period_sum += span(c, c->last_rise, tick);         /* 逐段取模再加：每段 < 一圈即可，总长可超过一圈 */
    c->last_rise = tick;
    if (++c->count < c->c.periods) return;
    if (c->period_sum) {
        c->freq_mhz = (uint32_t)(((uint64_t)c->c.timer_hz * 1000u * c->count + c->period_sum / 2u) / c->period_sum);
        c->duty = c->high_valid ? (float)((double)c->high_sum / (double)c->period_sum) : NAN;
        c->seq++;
    }
    c->count = 0; c->period_sum = 0; c->high_sum = 0; c->high_valid = false;
}

bool capfreq_read(const capfreq_t *c, uint32_t now_ms, uint32_t *freq_mhz, float *duty)
{
    if (!c || !c->seq || now_ms - c->last_edge_ms > c->c.timeout_ms) return false;
    if (freq_mhz) *freq_mhz = c->freq_mhz;
    if (duty) *duty = c->duty;
    return true;
}

dz_err_t capfreq_selftest(void)
{
    capfreq_t c; capfreq_cfg_t cfg = { 1000000u, 65536u, 4u, 100u };
    if (capfreq_init(&c, &cfg)) return DZ_EFAIL;
    for (uint32_t i = 0; i <= 4u; i++) { capfreq_edge(&c, (i * 1000u) % 65536u, true, i); capfreq_edge(&c, (i * 1000u + 250u) % 65536u, false, i); }
    uint32_t f = 0; float du = 0.0f;
    if (!capfreq_read(&c, 5, &f, &du) || f != 1000000u || fabsf(du - 0.25f) > 1e-4f) return DZ_EFAIL;
    return DZ_OK;
}
