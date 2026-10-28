#include "motor_2pwm.h"
#include <math.h>

motor_2pwm_cfg_t motor_2pwm_cfg_default(pal_id_t in1, pal_id_t in2)
{
    motor_2pwm_cfg_t c = { in1, in2, MOTOR_2PWM_SLOW_DECAY, false, 0.0f, 1.0f };
    return c;
}

static uint16_t to_duty(float d)
{
    if (!(d > 0.0f)) return 0u;
    if (d >= 1.0f) return (uint16_t)PAL_DUTY_MAX;
    return (uint16_t)(d * (float)PAL_DUTY_MAX + 0.5f);
}

void motor_2pwm_duties(const motor_2pwm_cfg_t *c, float cmd, uint16_t *d1, uint16_t *d2)
{
    uint16_t a = 0u, b = 0u;
    if (c && d1 && d2) {
        if (isnan(cmd)) cmd = 0.0f;
        if (cmd > 1.0f) cmd = 1.0f;
        if (cmd < -1.0f) cmd = -1.0f;
        if (c->invert) cmd = -cmd;
        float mag = fabsf(cmd);
        if (mag > 0.0f) {
            float duty = c->deadband + mag * (c->max_duty - c->deadband);
            uint16_t on = to_duty(duty);
            if (c->decay == MOTOR_2PWM_FAST_DECAY) { a = cmd > 0.0f ? on : 0u; b = cmd > 0.0f ? 0u : on; }
            else {
                uint16_t inv = (uint16_t)(PAL_DUTY_MAX - on);
                a = cmd > 0.0f ? (uint16_t)PAL_DUTY_MAX : inv;
                b = cmd > 0.0f ? inv : (uint16_t)PAL_DUTY_MAX;
            }
        }
        *d1 = a; *d2 = b;
    }
}

dz_err_t motor_2pwm_init(motor_2pwm_t *m, const motor_2pwm_cfg_t *c)
{
    if (!m || !c) return DZ_EINVAL;
    m->ready = false;
    if (c->in1 == c->in2 || c->decay > MOTOR_2PWM_SLOW_DECAY) return DZ_EINVAL;
    if (!(c->deadband >= 0.0f && c->deadband <= 0.5f) || !(c->max_duty > 0.0f && c->max_duty <= 1.0f)) return DZ_EINVAL;
    if (c->deadband >= c->max_duty) return DZ_EINVAL;
    uint32_t f1 = 0, f2 = 0;
    dz_err_t e = pal_pwm_get_freq(c->in1, &f1);
    if (e != DZ_OK) return e;
    if ((e = pal_pwm_get_freq(c->in2, &f2)) != DZ_OK) return e;
    if (f1 != f2) return DZ_EINVAL;
    m->cfg = *c; m->cmd = 0.0f;
    m->ready = true;
    return motor_2pwm_stop(m, false);
}

static dz_err_t apply(motor_2pwm_t *m, uint16_t a, uint16_t b)
{
    /* 两路是独立输入（不存在上下桥直通），顺序无所谓；DRV8833 内部自带死区 */
    dz_err_t e = pal_pwm_set_duty(m->cfg.in1, a);
    if (e != DZ_OK) return e;
    return pal_pwm_set_duty(m->cfg.in2, b);
}

dz_err_t motor_2pwm_set(motor_2pwm_t *m, float cmd)
{
    if (!m || !m->ready) return DZ_ESTATE;
    uint16_t a, b;
    motor_2pwm_duties(&m->cfg, cmd, &a, &b);
    m->cmd = isnan(cmd) ? 0.0f : (cmd > 1.0f ? 1.0f : (cmd < -1.0f ? -1.0f : cmd));
    return apply(m, a, b);
}

dz_err_t motor_2pwm_stop(motor_2pwm_t *m, bool brake)
{
    if (!m || !m->ready) return DZ_ESTATE;
    m->cmd = 0.0f;
    uint16_t v = brake ? (uint16_t)PAL_DUTY_MAX : 0u;
    return apply(m, v, v);
}

dz_err_t motor_2pwm_selftest(void)
{
    motor_2pwm_cfg_t c = motor_2pwm_cfg_default(0, 1);
    uint16_t a, b;
    motor_2pwm_duties(&c, 0.3f, &a, &b);
    if (a != PAL_DUTY_MAX || b != 7000u) return DZ_EFAIL;
    motor_2pwm_duties(&c, -0.3f, &a, &b);
    if (a != 7000u || b != PAL_DUTY_MAX) return DZ_EFAIL;
    c.decay = MOTOR_2PWM_FAST_DECAY;
    motor_2pwm_duties(&c, 0.3f, &a, &b);
    if (a != 3000u || b != 0u) return DZ_EFAIL;
    motor_2pwm_duties(&c, 0.0f, &a, &b);
    if (a != 0u || b != 0u) return DZ_EFAIL;
    return DZ_OK;
}
