#include "servo.h"
#include <math.h>

servo_cfg_t servo_cfg_default(pal_id_t pwm)
{
    servo_cfg_t c = { pwm, 500u, 2500u, 1500u, 0, 90.0f, -90.0f, 90.0f, 0.0f, false };
    return c;
}

static float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

uint16_t servo_deg_to_us(const servo_cfg_t *c, float deg)
{
    if (!c || !(c->half_range_deg > 0.0f)) return 0u;
    float d = c->invert ? -deg : deg;
    float us = (float)c->center_us + (float)c->trim_us
             + d / c->half_range_deg * ((float)c->max_us - (float)c->min_us) * 0.5f;
    us = clampf(us, (float)c->min_us, (float)c->max_us);
    return (uint16_t)(us + 0.5f);
}

static dz_err_t out(servo_t *s)
{
    s->pulse_us = servo_deg_to_us(&s->cfg, s->angle);
    return pal_pwm_set_pulse_us(s->cfg.pwm, s->pulse_us);
}

dz_err_t servo_init(servo_t *s, const servo_cfg_t *c)
{
    if (!s || !c) return DZ_EINVAL;
    s->ready = false;
    if (c->min_us < 300u || c->max_us > 3000u || c->min_us >= c->max_us) return DZ_EINVAL;
    if (c->center_us <= c->min_us || c->center_us >= c->max_us) return DZ_EINVAL;
    if (c->trim_us < -300 || c->trim_us > 300) return DZ_EINVAL;
    if (!(c->half_range_deg > 0.0f) || !(c->lim_lo_deg < c->lim_hi_deg)) return DZ_EINVAL;
    if (!(c->slew_dps >= 0.0f)) return DZ_EINVAL;
    s->cfg = *c;
    s->target = s->angle = clampf(0.0f, c->lim_lo_deg, c->lim_hi_deg);
    dz_err_t e = out(s);
    if (e != DZ_OK) return e;
    s->ready = true;
    return DZ_OK;
}

dz_err_t servo_set_deg(servo_t *s, float deg)
{
    if (!s || !s->ready) return DZ_ESTATE;
    if (isnan(deg)) return DZ_EINVAL;
    s->target = clampf(deg, s->cfg.lim_lo_deg, s->cfg.lim_hi_deg);
    if (s->cfg.slew_dps > 0.0f) return DZ_OK;
    s->angle = s->target;
    return out(s);
}

dz_err_t servo_set_us(servo_t *s, uint16_t us)
{
    if (!s || !s->ready) return DZ_ESTATE;
    if (us < s->cfg.min_us) us = s->cfg.min_us;
    if (us > s->cfg.max_us) us = s->cfg.max_us;
    s->pulse_us = us;
    return pal_pwm_set_pulse_us(s->cfg.pwm, us);
}

dz_err_t servo_tick(servo_t *s, float dt_s)
{
    if (!s || !s->ready) return DZ_ESTATE;
    if (!(dt_s >= 0.0f) || dt_s > 1.0f) return DZ_EINVAL;
    if (s->cfg.slew_dps <= 0.0f || s->angle == s->target) return DZ_OK;
    float step = s->cfg.slew_dps * dt_s, d = s->target - s->angle;
    s->angle = fabsf(d) <= step ? s->target : s->angle + (d > 0.0f ? step : -step);
    return out(s);
}

dz_err_t servo_selftest(void)
{
    servo_cfg_t c = servo_cfg_default(PAL_ID_NONE);
    if (servo_deg_to_us(&c, 0.0f) != 1500u) return DZ_EFAIL;
    if (servo_deg_to_us(&c, 90.0f) != 2500u || servo_deg_to_us(&c, -45.0f) != 1000u) return DZ_EFAIL;
    if (servo_deg_to_us(&c, 200.0f) != 2500u) return DZ_EFAIL;
    c.invert = true; c.trim_us = 20;
    if (servo_deg_to_us(&c, 45.0f) != 1020u) return DZ_EFAIL;
    return DZ_OK;
}
