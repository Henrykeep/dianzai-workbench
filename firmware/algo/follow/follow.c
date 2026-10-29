/* 跟车间距控制，见 follow.h。 */
#include <math.h>
#include <string.h>
#include "follow.h"

dz_err_t follow_init(follow_t *f, const follow_cfg_t *c)
{
    if (!f || !c || !(c->gap_ref_m > c->gap_min_m) || !(c->gap_min_m >= 0.0f) || !(c->kp >= 0.0f) || !(c->kd >= 0.0f) ||
        !(c->v_max > 0.0f) || !(c->accel > 0.0f) || !(c->decel > 0.0f))
        return DZ_EINVAL;
    memset(f, 0, sizeof *f);
    f->c = *c;
    return DZ_OK;
}

float follow_step(follow_t *f, bool lead_ok, float gap_m, float v_lead, float v_self, float dt_s)
{
    float tgt;
    if (!(dt_s > 0.0f)) return f->v;
    if (lead_ok && !(isfinite(gap_m) && isfinite(v_lead) && isfinite(v_self))) lead_ok = false;
    if (!lead_ok) {
        f->st = FOLLOW_LINK_LOST;
        tgt = 0.0f;
    } else if (gap_m < f->c.gap_min_m) {
        f->st = FOLLOW_TOO_CLOSE;
        f->v = 0.0f;
        return 0.0f;
    } else {
        f->st = FOLLOW_OK;
        tgt = v_lead + f->c.kp * (gap_m - f->c.gap_ref_m) - f->c.kd * (v_self - v_lead);
    }
    if (tgt > f->c.v_max) tgt = f->c.v_max;
    if (tgt < 0.0f) tgt = 0.0f;
    if (tgt > f->v + f->c.accel * dt_s) tgt = f->v + f->c.accel * dt_s;
    if (tgt < f->v - f->c.decel * dt_s) tgt = f->v - f->c.decel * dt_s;
    f->v = tgt;
    return tgt;
}

dz_err_t follow_selftest(void)
{
    follow_cfg_t c = { 0.5f, 0.2f, 1.0f, 0.2f, 1.0f, 2.0f, 4.0f };
    follow_t f;
    float v = 0.0f;
    int fail = 0, i;
    if (follow_init(&f, &c) != DZ_OK) return DZ_EINVAL;
    for (i = 0; i < 100; i++) v = follow_step(&f, true, 0.8f, 0.3f, v, 0.01f);
    fail += f.st != FOLLOW_OK || fabsf(v - 0.55f) > 0.01f;                /* 远了：v = 0.3 + 1·0.3 − 0.2·(v − 0.3) → 0.55 */
    fail += follow_step(&f, true, 0.1f, 0.3f, v, 0.01f) != 0.0f || f.st != FOLLOW_TOO_CLOSE;
    f.v = 0.8f;
    v = follow_step(&f, false, 0.5f, 0.3f, 0.8f, 0.01f);
    fail += f.st != FOLLOW_LINK_LOST || fabsf(v - 0.76f) > 1e-4f;         /* 断链：按 decel 减速，不急刹 */
    c.gap_min_m = 0.6f; fail += follow_init(&f, &c) != DZ_EINVAL;
    return fail ? DZ_EINVAL : DZ_OK;
}
