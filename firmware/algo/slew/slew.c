#include "slew.h"
#include <math.h>

static bool fin(float x) { return isfinite(x) != 0; }

dz_err_t slew_init(slew_t *s, const slew_cfg_t *cfg, float y0)
{
    if (s == 0 || cfg == 0) return DZ_EINVAL;
    if (!fin(cfg->rise_per_s) || !fin(cfg->fall_per_s) || !fin(y0)) return DZ_EINVAL;
    if (cfg->rise_per_s < 0.0f || cfg->fall_per_s < 0.0f) return DZ_EINVAL;
    if (cfg->mode != SLEW_BY_DIR && cfg->mode != SLEW_BY_MAG) return DZ_EINVAL;
    s->cfg = *cfg; s->y = y0; s->ready = true;
    return DZ_OK;
}

/* 从 y 朝 t 走，最多 rate*dt；rate=0 不限。 */
static float step_to(float y, float t, float rate, float dt)
{
    if (rate <= 0.0f) return t;
    float d = rate * dt;
    if (t > y + d) return y + d;
    if (t < y - d) return y - d;
    return t;
}

float slew_update(slew_t *s, float target, float dt_s)
{
    if (s == 0 || !s->ready) return 0.0f;
    if (!fin(target) || !fin(dt_s) || dt_s <= 0.0f) return s->y;
    float y = s->y, r = s->cfg.rise_per_s, f = s->cfg.fall_per_s;
    if (s->cfg.mode == SLEW_BY_DIR) {
        y = step_to(y, target, target >= y ? r : f, dt_s);
    } else {
        bool cross = (y > 0.0f && target < 0.0f) || (y < 0.0f && target > 0.0f);
        if (cross) {
            /* 先减速到 0（fall），剩余时间再加速（rise） */
            float t0 = (f > 0.0f) ? fabsf(y) / f : 0.0f;
            if (t0 >= dt_s) {
                y = step_to(y, 0.0f, f, dt_s);
            } else {
                y = step_to(0.0f, target, r, dt_s - t0);
            }
        } else {
            bool away = fabsf(target) > fabsf(y);
            y = step_to(y, target, away ? r : f, dt_s);
        }
    }
    s->y = y;
    return y;
}

void slew_reset(slew_t *s, float y)
{
    if (s != 0 && fin(y)) s->y = y;
}

dz_err_t slew_selftest(void)
{
    slew_t s; slew_cfg_t c = { 1.0f, 10.0f, SLEW_BY_MAG };
    if (slew_init(&s, &c, 0.0f) != DZ_OK) return DZ_EFAIL;
    if (fabsf(slew_update(&s, 1.0f, 0.1f) - 0.1f) > 1e-6f) return DZ_EFAIL;   /* 加速慢 */
    slew_reset(&s, 1.0f);
    if (fabsf(slew_update(&s, 0.0f, 0.05f) - 0.5f) > 1e-6f) return DZ_EFAIL;  /* 减速快 */
    return DZ_OK;
}
