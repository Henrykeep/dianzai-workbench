#include "line_sensor.h"

line_cfg_t line_cfg_default(void)
{
    line_cfg_t c;
    c.n = 0; c.analog = false;
    for (unsigned i = 0; i < LINE_MAX_CH; i++) c.ids[i] = PAL_ID_NONE;
    c.line_high = true; c.pitch_mm = 15.0f; c.on_thr = 0.5f; c.lost_sum = 0.3f; c.cross_n = 0;
    return c;
}

dz_err_t line_init(line_sensor_t *l, const line_cfg_t *c)
{
    if (!l || !c) return DZ_EINVAL;
    l->ready = false;
    if (c->n == 0u || c->n > LINE_MAX_CH || !(c->pitch_mm > 0.0f)) return DZ_EINVAL;
    if (!(c->on_thr > 0.0f && c->on_thr < 1.0f) || !(c->lost_sum >= 0.0f) || c->cross_n > c->n) return DZ_EINVAL;
    l->cfg = *c;
    for (unsigned i = 0; i < LINE_MAX_CH; i++) { l->cmin[i] = 0u; l->cmax[i] = 4095u; }
    l->last_pos = 0.0f; l->calibrating = false; l->calibrated = !c->analog;
    l->ready = true;
    return DZ_OK;
}

static dz_err_t read_raw(const line_sensor_t *l, unsigned i, uint16_t *raw)
{
    if (l->cfg.analog) return pal_adc_read(l->cfg.ids[i], raw);
    bool on = false;
    dz_err_t e = pal_gpio_read(l->cfg.ids[i], &on);
    *raw = on ? 1u : 0u;
    return e;
}

dz_err_t line_calib_begin(line_sensor_t *l)
{
    if (!l || !l->ready || !l->cfg.analog) return DZ_ESTATE;
    for (unsigned i = 0; i < LINE_MAX_CH; i++) { l->cmin[i] = 0xFFFFu; l->cmax[i] = 0u; }
    l->calibrating = true; l->calibrated = false;
    return DZ_OK;
}

dz_err_t line_calib_feed(line_sensor_t *l)
{
    if (!l || !l->ready || !l->calibrating) return DZ_ESTATE;
    for (unsigned i = 0; i < l->cfg.n; i++) {
        uint16_t r = 0; dz_err_t e = read_raw(l, i, &r);
        if (e != DZ_OK) return e;
        if (r < l->cmin[i]) l->cmin[i] = r;
        if (r > l->cmax[i]) l->cmax[i] = r;
    }
    return DZ_OK;
}

dz_err_t line_calib_set(line_sensor_t *l, const uint16_t *cmin, const uint16_t *cmax)
{
    if (!l || !l->ready || !cmin || !cmax) return DZ_EINVAL;
    for (unsigned i = 0; i < l->cfg.n; i++)
        if (cmax[i] < cmin[i] + 50u) return DZ_EINVAL;   /* 动态范围太小：探头高度不对或没扫到线 */
    for (unsigned i = 0; i < l->cfg.n; i++) { l->cmin[i] = cmin[i]; l->cmax[i] = cmax[i]; }
    l->calibrating = false; l->calibrated = true;
    return DZ_OK;
}

dz_err_t line_calib_end(line_sensor_t *l)
{
    if (!l || !l->ready || !l->calibrating) return DZ_ESTATE;
    uint16_t a[LINE_MAX_CH], b[LINE_MAX_CH];
    for (unsigned i = 0; i < LINE_MAX_CH; i++) { a[i] = l->cmin[i]; b[i] = l->cmax[i]; }
    dz_err_t e = line_calib_set(l, a, b);
    if (e != DZ_OK) { l->calibrating = false; return DZ_EFAIL; }
    return DZ_OK;
}

dz_err_t line_compute(line_sensor_t *l, const float *w, line_result_t *o)
{
    if (!l || !l->ready) return DZ_ESTATE;
    if (!w || !o) return DZ_EINVAL;
    const line_cfg_t *c = &l->cfg;
    float sw = 0.0f, swx = 0.0f, half = ((float)c->n - 1.0f) * 0.5f;
    uint8_t mask = 0, cnt = 0;
    for (unsigned i = 0; i < c->n; i++) {
        float v = w[i];
        if (!(v >= 0.0f)) v = 0.0f;            /* 含 NaN */
        if (v > 1.0f) v = 1.0f;
        if (v >= c->on_thr) { mask |= (uint8_t)(1u << i); cnt++; }
        sw += v; swx += v * ((float)i - half) * c->pitch_mm;
    }
    o->strength = sw; o->mask = mask; o->flags = 0;
    if (c->cross_n && cnt >= c->cross_n) { o->flags |= LINE_F_CROSS; o->pos_mm = 0.0f; return DZ_OK; }
    if (sw < c->lost_sum || sw <= 0.0f) {
        o->flags |= LINE_F_LOST;
        float edge = half * c->pitch_mm;
        o->pos_mm = l->last_pos < 0.0f ? -edge : (l->last_pos > 0.0f ? edge : 0.0f);
        return DZ_OK;
    }
    o->pos_mm = swx / sw;
    l->last_pos = o->pos_mm;
    return DZ_OK;
}

dz_err_t line_read(line_sensor_t *l, line_result_t *o)
{
    if (!l || !l->ready || (l->cfg.analog && !l->calibrated)) return DZ_ESTATE;
    float w[LINE_MAX_CH];
    for (unsigned i = 0; i < l->cfg.n; i++) {
        uint16_t r = 0; dz_err_t e = read_raw(l, i, &r);
        if (e != DZ_OK) return e;
        if (!l->cfg.analog) { w[i] = (float)r; continue; }
        float v = ((float)r - (float)l->cmin[i]) / (float)(l->cmax[i] - l->cmin[i]);
        w[i] = l->cfg.line_high ? v : 1.0f - v;
    }
    return line_compute(l, w, o);
}

dz_err_t line_sensor_selftest(void)
{
    line_sensor_t l; line_cfg_t c = line_cfg_default();
    c.n = 5; c.pitch_mm = 10.0f; c.cross_n = 4;
    if (line_init(&l, &c) != DZ_OK) return DZ_EFAIL;
    line_result_t r;
    const float mid[5] = { 0, 0, 1, 0, 0 }, rr[5] = { 0, 0, 0, 1, 1 }, none[5] = { 0 }, all[5] = { 1, 1, 1, 1, 0 };
    if (line_compute(&l, mid, &r) != DZ_OK || r.pos_mm != 0.0f || r.mask != 0x04u) return DZ_EFAIL;
    (void)line_compute(&l, rr, &r); if (r.pos_mm != 15.0f) return DZ_EFAIL;
    (void)line_compute(&l, none, &r); if (!(r.flags & LINE_F_LOST) || r.pos_mm != 20.0f) return DZ_EFAIL;
    (void)line_compute(&l, all, &r); if (!(r.flags & LINE_F_CROSS)) return DZ_EFAIL;
    return DZ_OK;
}
