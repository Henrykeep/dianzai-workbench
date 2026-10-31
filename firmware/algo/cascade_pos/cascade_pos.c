#include "cascade_pos.h"
#include <math.h>

static float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }
static bool fin(float v) { return v == v && !isinf(v); }

dz_err_t cascade_pos_init(cascade_pos_t *b, const cascade_pos_cfg_t *c)
{
    if (!b || !c) return DZ_EINVAL;
    if (!(c->alpha > 0.0f && c->alpha <= 1.0f) || !(c->beta >= 0.0f && c->beta < 4.0f - 2.0f * c->alpha) ||
        !(c->lead_s >= 0.0f) || !(c->vel_max > 0.0f) || !(c->angle_max > 0.0f) || !(c->i_max >= 0.0f) ||
        !(c->i_decay >= 0.0f && c->i_decay <= 1.0f) || !fin(c->pos_k) || !fin(c->vel_k) || !fin(c->ki) ||
        c->timeout_ms < c->hold_ms || (c->dir != 1.0f && c->dir != -1.0f))
        return DZ_EINVAL;
    if (c->est_mode > 1u || c->loop_mode > 1u || !(c->est_lpf >= 0.0f && c->est_lpf <= 1.0f) ||
        !(c->stic_deg >= 0.0f) || !(c->stic_vel >= 0.0f) || !(c->stic_e >= 0.0f) || !(c->i_vel >= 0.0f) || !(c->i_leak >= 0.0f && c->i_leak < 1.0f) || c->bal_n > BB_BAL_MAX)
        return DZ_EINVAL;
    for (uint8_t i = 0; i < c->bal_n; i++)
        if (!fin(c->bal_x[i]) || !fin(c->bal_deg[i]) || (i && !(c->bal_x[i] > c->bal_x[i - 1u]))) return DZ_EINVAL;
    b->cfg = *c;
    b->out = 0.0f;
    cascade_pos_reset(b);
    return DZ_OK;
}

void cascade_pos_reset(cascade_pos_t *b)
{
    if (!b) return;
    b->primed = false; b->x = b->v = 0.0f; b->t_sample = 0u;
    b->integ = 0.0f; b->e_prev = 0.0f; b->new_sample = false; b->state = CPOS_WAIT;
}

void cascade_pos_sample(cascade_pos_t *b, float z, uint32_t t)
{
    float dt;
    if (!b || !fin(z)) return;
    dt = (float)(int32_t)(t - b->t_sample) * 1e-3f;
    if (!b->primed || b->state == CPOS_LOST || dt <= 0.0f || dt > 0.5f) {
        if (b->primed && dt <= 0.0f && b->state != CPOS_LOST) return;     /* 乱序/重复样本丢弃 */
        b->x = z; b->v = 0.0f; b->primed = true;
    } else {
        if (b->cfg.est_mode == BB_EST_DIFF_LPF) {              /* B：差分 + 一阶低通 */
            float k = b->cfg.est_lpf > 0.0f ? b->cfg.est_lpf : 0.3f;
            b->v += k * ((z - b->x) / dt - b->v);
            b->x = z;
        } else {                                               /* A：α-β */
            float xp = b->x + b->v * dt, r = z - xp;
            b->x = xp + b->cfg.alpha * r;
            b->v += b->cfg.beta * r / dt;
        }
    }
    b->t_sample = t; b->new_sample = true;
    if (b->state == CPOS_LOST || b->state == CPOS_WAIT) b->state = CPOS_TRACK;
}

float cascade_pos_bal_ff(const cascade_pos_cfg_t *c, float x)
{
    if (!c || c->bal_n < 2u || !fin(x)) return 0.0f;
    if (x <= c->bal_x[0]) return c->bal_deg[0];
    for (uint8_t i = 1; i < c->bal_n; i++)
        if (x <= c->bal_x[i])
            return c->bal_deg[i - 1u] + (c->bal_deg[i] - c->bal_deg[i - 1u]) * (x - c->bal_x[i - 1u]) / (c->bal_x[i] - c->bal_x[i - 1u]);
    return c->bal_deg[c->bal_n - 1u];
}

float cascade_pos_update(cascade_pos_t *b, float sp, float ff, uint32_t now, float dt)
{
    const cascade_pos_cfg_t *c;
    uint32_t age;
    float target, step;
    if (!b) return 0.0f;
    c = &b->cfg;
    if (!fin(sp)) sp = 0.0f;
    if (!fin(ff)) ff = 0.0f;
    if (!(dt > 0.0f) || !fin(dt)) dt = 0.0f;
    age = b->primed ? (uint32_t)(now - b->t_sample) : 0xFFFFFFFFu;

    if (!b->primed || age > c->timeout_ms) {
        if (b->primed) { b->state = CPOS_LOST; b->primed = false; }
        b->integ = 0.0f;
        target = 0.0f;
    } else if (age > c->hold_ms) {
        b->state = CPOS_HOLD;
        target = b->out;
    } else {
        float x_now = b->x + b->v * ((float)age * 1e-3f + c->lead_s);
        float e = sp - x_now, v_des;
        b->state = CPOS_TRACK;
        if (b->new_sample && c->i_zone > 0.0f && fabsf(e) < c->i_zone && !(c->i_vel > 0.0f && fabsf(b->v) >= c->i_vel)) {
            if (e * b->e_prev < 0.0f) b->integ *= c->i_decay;
            b->integ = clampf(b->integ + c->ki * e * dt, -c->i_max, c->i_max);
        } else if (b->new_sample && c->i_leak > 0.0f) {
            b->integ *= c->i_leak;
        }
        if (b->new_sample) b->e_prev = e;
        b->new_sample = false;
        v_des = c->loop_mode == BB_LOOP_SINGLE ? c->pos_k * e : clampf(c->pos_k * e, -c->vel_max, c->vel_max);
        target = c->dir * (c->vel_k * (v_des - b->v) + b->integ) + ff;
        if (c->stic_deg > 0.0f && fabsf(b->v) < c->stic_vel && fabsf(e) > c->stic_e)
            target += c->dir * (e > 0.0f ? c->stic_deg : -c->stic_deg);
        target += cascade_pos_bal_ff(c, x_now);
    }
    target = clampf(target, -c->angle_max, c->angle_max);
    step = (c->rate_max > 0.0f) ? c->rate_max * dt : INFINITY;
    b->out = clampf(target, b->out - step, b->out + step);
    return b->out;
}

cascade_pos_state_t cascade_pos_state(const cascade_pos_t *b) { return b ? b->state : CPOS_WAIT; }

dz_err_t cascade_pos_selftest(void)
{
    cascade_pos_cfg_t c = { 0.55f, 0.20f, 0.07f, 0.72f, 320.0f, 0.016f, 0.055f, 55.0f, 2.5f, 0.5f,
                          5.5f, 220.0f, 120u, 600u, 1.0f, 0u, 0.0f, 0u, 0.0f, 0.0f, 0.0f, 0u, {0}, {0}, 0.0f, 0.0f };
    cascade_pos_t b;
    float a = 0.0f;
    uint32_t t;
    if (cascade_pos_init(&b, &c) != DZ_OK) return DZ_EFAIL;
    for (t = 0u; t <= 500u; t += 10u) {
        if (t % 40u == 0u) cascade_pos_sample(&b, -100.0f, t);
        a = cascade_pos_update(&b, 0.0f, 0.0f, t, 0.01f);
    }
    if (!(a > 0.5f && a <= 5.5f) || cascade_pos_state(&b) != CPOS_TRACK) return DZ_EFAIL;   /* 对象在 −x → 正角推回 */
    for (; t <= 1500u; t += 10u) a = cascade_pos_update(&b, 0.0f, 0.0f, t, 0.01f);
    return (cascade_pos_state(&b) == CPOS_LOST && fabsf(a) < 1e-6f) ? DZ_OK : DZ_EFAIL;
}
