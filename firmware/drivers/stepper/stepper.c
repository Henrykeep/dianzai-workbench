#include "stepper.h"

stepper_cfg_t stepper_cfg_default(pal_id_t step, pal_id_t dir, pal_id_t en)
{
    stepper_cfg_t c = { step, dir, en, false, 20000u, 4000u, 200u, 8000u };
    return c;
}

static uint32_t sps_to_inc(uint32_t sps, uint32_t hz) { return (uint32_t)(((uint64_t)sps << 32) / hz); }

uint32_t stepper_stop_steps(uint32_t inc, uint32_t ainc)
{
    if (ainc == 0u) return UINT32_MAX;
    uint64_t q = ((uint64_t)inc * inc) / (2u * (uint64_t)ainc);
    return (uint32_t)(q >> 32);
}

dz_err_t stepper_init(stepper_t *s, const stepper_cfg_t *c)
{
    if (!s || !c) return DZ_EINVAL;
    s->ready = false;
    if (c->tick_hz < 1000u || c->tick_hz > 200000u) return DZ_EINVAL;
    if (c->max_sps == 0u || c->max_sps > c->tick_hz / 2u) return DZ_EINVAL;
    if (c->start_sps == 0u || c->start_sps > c->max_sps || c->acc_sps2 == 0u) return DZ_EINVAL;
    uint64_t ainc = ((uint64_t)c->acc_sps2 << 32) / ((uint64_t)c->tick_hz * c->tick_hz);
    if (ainc == 0u || ainc > 0x7FFFFFFFu) return DZ_EINVAL;   /* 加速度相对 tick 太小/太大 */
    s->cfg = *c;
    s->ainc = (uint32_t)ainc;
    s->vmax_inc = sps_to_inc(c->max_sps, c->tick_hz);
    s->vmin_inc = sps_to_inc(c->start_sps, c->tick_hz);
    s->pos = s->target = 0; s->inc = 0; s->phase = 0; s->dir = 1;
    s->pulse_high = false; s->dir_settle = false; s->halt = false; s->enabled = false;
    dz_err_t e = pal_gpio_write(c->step, false);
    if (e != DZ_OK) return e;
    if ((e = pal_gpio_write(c->dir, c->invert_dir)) != DZ_OK) return e;
    if (c->en != PAL_ID_NONE && (e = pal_gpio_write(c->en, false)) != DZ_OK) return e;
    s->ready = true;
    return DZ_OK;
}

dz_err_t stepper_enable(stepper_t *s, bool on)
{
    if (!s || !s->ready) return DZ_ESTATE;
    s->enabled = on;
    if (!on) { s->inc = 0; s->target = s->pos; }
    return s->cfg.en != PAL_ID_NONE ? pal_gpio_write(s->cfg.en, on) : DZ_OK;
}

dz_err_t stepper_move_to(stepper_t *s, int32_t t)
{
    if (!s || !s->ready || !s->enabled) return DZ_ESTATE;
    uint32_t k = pal_irq_save();
    s->target = t; s->halt = false;
    pal_irq_restore(k);
    return DZ_OK;
}

dz_err_t stepper_move_rel(stepper_t *s, int32_t d)
{
    if (!s || !s->ready) return DZ_ESTATE;
    int64_t t = (int64_t)s->target + d;
    if (t > INT32_MAX || t < INT32_MIN) return DZ_EINVAL;
    return stepper_move_to(s, (int32_t)t);
}

dz_err_t stepper_stop(stepper_t *s)
{
    if (!s || !s->ready) return DZ_ESTATE;
    uint32_t k = pal_irq_save();
    uint32_t d = stepper_stop_steps(s->inc, s->ainc) + 1u;
    s->target = s->inc ? s->pos + s->dir * (int32_t)d : s->pos;
    pal_irq_restore(k);
    return DZ_OK;
}

dz_err_t stepper_halt(stepper_t *s)
{
    if (!s || !s->ready) return DZ_ESTATE;
    uint32_t k = pal_irq_save();
    s->halt = true; s->inc = 0; s->target = s->pos;
    pal_irq_restore(k);
    return DZ_OK;
}

dz_err_t stepper_set_pos(stepper_t *s, int32_t p)
{
    if (!s || !s->ready) return DZ_ESTATE;
    if (s->inc != 0u) return DZ_EBUSY;
    uint32_t k = pal_irq_save();
    s->pos = s->target = p;
    pal_irq_restore(k);
    return DZ_OK;
}

void stepper_tick(stepper_t *s)
{
    if (!s || !s->ready) return;
    if (s->pulse_high) { (void)pal_gpio_write(s->cfg.step, false); s->pulse_high = false; return; }
    if (s->halt || !s->enabled) return;
    if (s->dir_settle) { s->dir_settle = false; return; }

    int32_t err = s->target - s->pos;
    if (err == 0 && s->inc <= s->vmin_inc) { s->inc = 0; s->phase = 0; return; }
    int8_t want = err > 0 ? 1 : (err < 0 ? -1 : s->dir);

    if (s->inc == 0u) {
        if (want != s->dir) {          /* 静止时才换向 */
            s->dir = want;
            (void)pal_gpio_write(s->cfg.dir, (want < 0) != s->cfg.invert_dir);
            s->dir_settle = true;
            return;
        }
        s->inc = s->vmin_inc;
    } else {
        uint32_t remain = want == s->dir ? (uint32_t)(err < 0 ? -err : err) : 0u;
        uint32_t brake = stepper_stop_steps(s->inc, s->ainc);
        if (remain <= brake) {         /* 减速（包括反向目标：先减到 0） */
            if (want != s->dir) s->inc = s->inc > s->ainc ? s->inc - s->ainc : 0u;
            else s->inc = s->inc > s->vmin_inc + s->ainc ? s->inc - s->ainc : s->vmin_inc;
            if (s->inc == 0u) { s->phase = 0; return; }
        } else if (s->inc < s->vmax_inc) {
            s->inc = s->vmax_inc - s->inc > s->ainc ? s->inc + s->ainc : s->vmax_inc;
        }
    }
    if (want != s->dir && s->inc <= s->vmin_inc) { s->inc = 0; s->phase = 0; return; }
    uint32_t old = s->phase;
    s->phase += s->inc;
    if (s->phase < old) {              /* 相位溢出 = 走一步 */
        if (s->target == s->pos) return;
        (void)pal_gpio_write(s->cfg.step, true);
        s->pulse_high = true;
        s->pos += s->dir;
    }
}

int32_t stepper_pos(const stepper_t *s) { return s ? s->pos : 0; }
bool stepper_busy(const stepper_t *s) { return s && (s->inc != 0u || s->pos != s->target); }
uint32_t stepper_speed_sps(const stepper_t *s)
{
    return s ? (uint32_t)(((uint64_t)s->inc * s->cfg.tick_hz) >> 32) : 0u;
}

dz_err_t stepper_selftest(void)
{
    /* 20 kHz tick, 8000 sps² → ainc = 8000·2³²/4e8 ≈ 85899；4000 sps → inc ≈ 858993459
       刹车距离 = v²/(2a) = 4000²/16000 = 1000 步 */
    uint32_t inc = sps_to_inc(4000u, 20000u);
    uint32_t ainc = (uint32_t)(((uint64_t)8000u << 32) / 400000000u);
    uint32_t d = stepper_stop_steps(inc, ainc);
    if (d < 995u || d > 1005u) return DZ_EFAIL;
    if (stepper_stop_steps(0u, ainc) != 0u) return DZ_EFAIL;
    return DZ_OK;
}
