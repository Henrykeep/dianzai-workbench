#include "buzzer.h"

static const uint16_t s_beep[] = { 60 };
static const uint16_t s_ok[] = { 60, 80, 60 };
static const uint16_t s_err[] = { 300, 150, 300, 150, 300 };
static const uint16_t s_low[] = { 100, 2900 };
static const uint16_t s_alarm[] = { 120, 80 };
const buzzer_pattern_t BUZZER_BEEP   = { s_beep, 1, 1, 1 };
const buzzer_pattern_t BUZZER_OK     = { s_ok, 3, 1, 1 };
const buzzer_pattern_t BUZZER_ERROR  = { s_err, 5, 1, 2 };
const buzzer_pattern_t BUZZER_LOWBAT = { s_low, 2, 0, 3 };
const buzzer_pattern_t BUZZER_ALARM  = { s_alarm, 2, 0, 9 };

static dz_err_t drive(buzzer_t *b, bool on)
{
    b->on = on;
    if (b->pwm != PAL_ID_NONE) return pal_pwm_set_duty(b->pwm, on ? (uint16_t)(PAL_DUTY_MAX / 2u) : 0u);
    if (b->gpio != PAL_ID_NONE) return pal_gpio_write(b->gpio, on);
    return DZ_OK; /* 纯逻辑模式（测试） */
}

dz_err_t buzzer_init(buzzer_t *b, pal_id_t gpio, pal_id_t pwm)
{
    if (!b) return DZ_EINVAL;
    b->gpio = gpio; b->pwm = pwm; b->cur = 0; b->step = 0; b->rep_done = 0; b->step_at = 0;
    b->ready = false;
    dz_err_t e = drive(b, false);
    if (e != DZ_OK) return e;
    b->ready = true;
    return DZ_OK;
}

static bool valid(const buzzer_pattern_t *p)
{
    if (!p || !p->steps || p->n == 0u || p->n > BUZZER_MAX_STEPS) return false;
    if (p->repeat != 1u && (p->n & 1u)) return false; /* 要重复的节奏必须以“停”结尾，否则两轮连成一声 */
    for (uint8_t i = 0; i < p->n; i++) if (p->steps[i] == 0u) return false;
    return true;
}

dz_err_t buzzer_play(buzzer_t *b, const buzzer_pattern_t *p, uint32_t now_ms)
{
    if (!b || !b->ready) return DZ_ESTATE;
    if (!valid(p)) return DZ_EINVAL;
    if (b->cur && b->cur->prio > p->prio) return DZ_EBUSY;
    b->cur = p; b->step = 0; b->rep_done = 0; b->step_at = now_ms;
    return drive(b, true);
}

dz_err_t buzzer_stop(buzzer_t *b)
{
    if (!b || !b->ready) return DZ_ESTATE;
    b->cur = 0;
    return drive(b, false);
}

dz_err_t buzzer_tick(buzzer_t *b, uint32_t now_ms)
{
    if (!b || !b->ready) return DZ_ESTATE;
    dz_err_t e = DZ_OK;
    /* 一次 tick 最多推进 n 步，防止长时间没调用后空转 */
    for (unsigned guard = 0; b->cur && guard <= BUZZER_MAX_STEPS; guard++) {
        const buzzer_pattern_t *p = b->cur;
        if ((uint32_t)(now_ms - b->step_at) < p->steps[b->step]) break;
        b->step_at += p->steps[b->step];
        b->step++;
        if (b->step >= p->n) {
            b->step = 0;
            if (p->repeat != 0u && ++b->rep_done >= p->repeat) { b->cur = 0; e = drive(b, false); break; }
        }
        e = drive(b, (b->step & 1u) == 0u);
    }
    return e;
}

bool buzzer_busy(const buzzer_t *b) { return b && b->cur; }
bool buzzer_is_on(const buzzer_t *b) { return b && b->on; }

dz_err_t buzzer_selftest(void)
{
    buzzer_t b;
    if (buzzer_init(&b, PAL_ID_NONE, PAL_ID_NONE) != DZ_OK) return DZ_EFAIL;
    if (buzzer_play(&b, &BUZZER_OK, 0) != DZ_OK || !b.on) return DZ_EFAIL;
    (void)buzzer_tick(&b, 59);  if (!b.on) return DZ_EFAIL;
    (void)buzzer_tick(&b, 60);  if (b.on) return DZ_EFAIL;
    (void)buzzer_tick(&b, 140); if (!b.on) return DZ_EFAIL;
    (void)buzzer_tick(&b, 200); if (b.on || buzzer_busy(&b)) return DZ_EFAIL;
    if (buzzer_play(&b, &BUZZER_ALARM, 300) != DZ_OK) return DZ_EFAIL;
    if (buzzer_play(&b, &BUZZER_BEEP, 310) != DZ_EBUSY) return DZ_EFAIL;
    return DZ_OK;
}
