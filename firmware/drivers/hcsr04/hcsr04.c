#include "hcsr04.h"

hcsr04_cfg_t hcsr04_cfg_default(pal_id_t trig, pal_id_t echo)
{
    hcsr04_cfg_t c = { trig, echo, 60u, 25000u, 20u, 4000u };
    return c;
}

dz_err_t hcsr04_set_temp(hcsr04_t *h, float t)
{
    if (!h || !(t >= -20.0f && t <= 60.0f)) return DZ_EINVAL;
    h->c_mm_per_us = (331.3f + 0.606f * t) * 0.001f;   /* m/s → mm/us */
    return DZ_OK;
}

dz_err_t hcsr04_init(hcsr04_t *h, const hcsr04_cfg_t *c)
{
    if (!h || !c) return DZ_EINVAL;
    h->ready = false;
    if (c->period_ms < 60u || c->timeout_us < 1000u || c->timeout_us > 60000u || c->min_mm >= c->max_mm) return DZ_EINVAL;
    h->cfg = *c;
    h->phase = HCSR04_IDLE; h->t_trig = h->t_rise = h->width_us = 0;
    h->last_level = false; h->last_start_ms = 0; h->dist_mm = 0.0f; h->valid = false; h->started = false;
    (void)hcsr04_set_temp(h, 20.0f);
    if (c->trig != PAL_ID_NONE) {
        dz_err_t e = pal_gpio_write(c->trig, false);
        if (e != DZ_OK) return e;
    }
    h->ready = true;
    return DZ_OK;
}

float hcsr04_width_to_mm(const hcsr04_t *h, uint32_t w)
{
    return h ? (float)w * h->c_mm_per_us * 0.5f : 0.0f;
}

dz_err_t hcsr04_trigger(hcsr04_t *h, uint32_t now_us)
{
    if (!h || !h->ready) return DZ_ESTATE;
    if (h->phase == HCSR04_WAIT_RISE || h->phase == HCSR04_WAIT_FALL) return DZ_EBUSY;
    dz_err_t e = DZ_OK;
    if (h->cfg.trig != PAL_ID_NONE) {
        if ((e = pal_gpio_write(h->cfg.trig, true)) != DZ_OK) return e;
        pal_delay_us(10u);
        if ((e = pal_gpio_write(h->cfg.trig, false)) != DZ_OK) return e;
    }
    h->t_trig = now_us;
    h->last_level = false;
    h->phase = HCSR04_WAIT_RISE;
    return DZ_OK;
}

void hcsr04_echo_edge(hcsr04_t *h, bool level, uint32_t now_us)
{
    if (!h) return;
    if (level && h->phase == HCSR04_WAIT_RISE) { h->t_rise = now_us; h->phase = HCSR04_WAIT_FALL; }
    else if (!level && h->phase == HCSR04_WAIT_FALL) { h->width_us = now_us - h->t_rise; h->phase = HCSR04_DONE; }
}

static void finish(hcsr04_t *h)
{
    float mm = hcsr04_width_to_mm(h, h->width_us);
    h->valid = mm >= (float)h->cfg.min_mm && mm <= (float)h->cfg.max_mm;
    h->dist_mm = mm;
}

dz_err_t hcsr04_poll(hcsr04_t *h, uint32_t now_us, bool read_pin)
{
    if (!h || !h->ready) return DZ_ESTATE;
    if (read_pin && (h->phase == HCSR04_WAIT_RISE || h->phase == HCSR04_WAIT_FALL)) {
        bool lv = false;
        dz_err_t e = pal_gpio_read(h->cfg.echo, &lv);
        if (e != DZ_OK) return e;
        if (lv != h->last_level) { hcsr04_echo_edge(h, lv, now_us); h->last_level = lv; }
    }
    if ((h->phase == HCSR04_WAIT_RISE || h->phase == HCSR04_WAIT_FALL)
        && (uint32_t)(now_us - h->t_trig) > h->cfg.timeout_us) {
        h->phase = HCSR04_TIMEOUT; h->valid = false;
    }
    return DZ_OK;
}

bool hcsr04_update(hcsr04_t *h, uint32_t now_ms, uint32_t now_us, bool read_pin)
{
    if (!h || !h->ready) return false;
    (void)hcsr04_poll(h, now_us, read_pin);
    bool fresh = false;
    if (h->phase == HCSR04_DONE) { finish(h); h->phase = HCSR04_IDLE; fresh = true; }
    else if (h->phase == HCSR04_TIMEOUT) { h->phase = HCSR04_IDLE; fresh = true; }
    if (h->phase == HCSR04_IDLE && (!h->started || (uint32_t)(now_ms - h->last_start_ms) >= h->cfg.period_ms)) {
        if (hcsr04_trigger(h, now_us) == DZ_OK) { h->last_start_ms = now_ms; h->started = true; }
    }
    return fresh;
}

bool hcsr04_valid(const hcsr04_t *h) { return h && h->valid; }
float hcsr04_mm(const hcsr04_t *h) { return h ? h->dist_mm : 0.0f; }

dz_err_t hcsr04_selftest(void)
{
    hcsr04_t h; hcsr04_cfg_t c = hcsr04_cfg_default(PAL_ID_NONE, PAL_ID_NONE);
    if (hcsr04_init(&h, &c) != DZ_OK) return DZ_EFAIL;
    /* 20 °C：c = 343.42 m/s；1 m 往返 5824 us */
    float mm = hcsr04_width_to_mm(&h, 5824u);
    if (mm < 998.0f || mm > 1002.0f) return DZ_EFAIL;
    if (hcsr04_trigger(&h, 0) != DZ_OK) return DZ_EFAIL;
    hcsr04_echo_edge(&h, true, 400); hcsr04_echo_edge(&h, false, 400 + 1165);
    if (h.phase != HCSR04_DONE || h.width_us != 1165u) return DZ_EFAIL;
    return DZ_OK;
}
