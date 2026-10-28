#include "abobs.h"
#include <math.h>
#include <stddef.h>

dz_err_t abobs_init(abobs_t *o, const abobs_cfg_t *cfg)
{
    if (!o || !cfg) return DZ_EINVAL;
    if (!(cfg->alpha > 0.0f && cfg->alpha <= 1.0f) || !(cfg->beta >= 0.0f && cfg->beta < 4.0f - 2.0f * cfg->alpha))
        return DZ_EINVAL;
    if (!(cfg->gate >= 0.0f) || !(cfg->max_predict_s >= 0.0f)) return DZ_EINVAL;
    *o = (abobs_t){0};
    o->cfg = *cfg;
    return DZ_OK;
}

void abobs_predict(abobs_t *o, float dt_s)
{
    if (!o || !o->primed || !(dt_s > 0.0f)) return;
    o->coast_s += dt_s;
    if (o->cfg.max_predict_s > 0.0f && o->coast_s > o->cfg.max_predict_s) { o->v = 0.0f; return; }
    o->x += o->v * dt_s;
}

bool abobs_update(abobs_t *o, float z, float dt_s)
{
    if (!o || !isfinite(z)) return false;
    if (!o->primed) { o->x = z; o->v = 0.0f; o->primed = true; o->coast_s = 0.0f; return true; }
    if (!(dt_s > 0.0f)) return false;
    float xp = o->x + o->v * dt_s;
    float r = z - xp;
    if (o->cfg.gate > 0.0f && fabsf(r) > o->cfg.gate) { o->rejected++; abobs_predict(o, dt_s); return false; }
    o->x = xp + o->cfg.alpha * r;
    o->v += o->cfg.beta / dt_s * r;
    o->coast_s = 0.0f;
    return true;
}

void abobs_reset(abobs_t *o, float x0)
{
    if (!o) return;
    o->x = x0; o->v = 0.0f; o->coast_s = 0.0f; o->primed = true;
}

dz_err_t abobs_selftest(void)
{
    abobs_t o; abobs_cfg_t c = { 0.5f, 0.1f, 0.0f, 0.0f };
    if (abobs_init(&o, &c) != DZ_OK) return DZ_EFAIL;
    for (int k = 0; k <= 200; k++) abobs_update(&o, 2.0f * (float)k * 0.01f, 0.01f);   /* 匀速 2 单位/秒 */
    return fabsf(o.v - 2.0f) < 0.05f && fabsf(o.x - 4.0f) < 0.05f ? DZ_OK : DZ_EFAIL;
}
