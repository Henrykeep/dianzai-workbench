#include "motor_dc.h"

static bool md_finite(float x) { return (x == x) && (x - x == 0.0f); }

motor_dc_cfg_t motor_dc_cfg_default(void)
{
    motor_dc_cfg_t c;
    c.mode = MOTOR_DC_PWM_IN1_IN2;
    c.pwm = PAL_ID_NONE;
    c.in1 = PAL_ID_NONE;
    c.in2 = PAL_ID_NONE;
    c.invert = false;
    c.deadband = 0.0f;
    c.max_duty = 1.0f;
    return c;
}

static dz_err_t md_check(const motor_dc_cfg_t *c)
{
    if (c == 0) return DZ_EINVAL;
    if (c->pwm == PAL_ID_NONE || c->in1 == PAL_ID_NONE) return DZ_EINVAL;
    if (c->mode == MOTOR_DC_PWM_IN1_IN2 && c->in2 == PAL_ID_NONE) return DZ_EINVAL;
    if (c->mode == MOTOR_DC_PWM_DIR && c->in2 != PAL_ID_NONE) return DZ_EINVAL;
    if (c->mode != MOTOR_DC_PWM_IN1_IN2 && c->mode != MOTOR_DC_PWM_DIR) return DZ_EINVAL;
    if (!md_finite(c->deadband) || c->deadband < 0.0f || c->deadband > 0.5f) return DZ_EINVAL;
    if (!md_finite(c->max_duty) || c->max_duty <= 0.0f || c->max_duty > 1.0f) return DZ_EINVAL;
    if (c->deadband >= c->max_duty) return DZ_EINVAL;
    return DZ_OK;
}

static uint16_t md_duty_raw(float d)
{
    if (d <= 0.0f) return 0;
    if (d >= 1.0f) return (uint16_t)PAL_DUTY_MAX;
    return (uint16_t)(d * (float)PAL_DUTY_MAX + 0.5f);
}

/* 写方向脚：dir=1 正转，-1 反转，0 滑行，2 刹车 */
static dz_err_t md_write_dir(const motor_dc_cfg_t *c, int dir)
{
    dz_err_t e;
    if (c->mode == MOTOR_DC_PWM_DIR) {
        if (dir == 1 || dir == -1) return pal_gpio_write(c->in1, dir == 1);
        return DZ_OK; /* DIR 模式滑行/刹车只靠占空比 0 */
    }
    bool a = (dir == 1 || dir == 2);
    bool b = (dir == -1 || dir == 2);
    e = pal_gpio_write(c->in1, a);
    if (e != DZ_OK) return e;
    return pal_gpio_write(c->in2, b);
}

dz_err_t motor_dc_init(motor_dc_t *m, const motor_dc_cfg_t *cfg)
{
    if (m == 0) return DZ_EINVAL;
    dz_err_t e = md_check(cfg);
    if (e != DZ_OK) return e;
    m->cfg = *cfg;
    m->cmd = 0.0f;
    m->dir = 0;
    m->ready = true;
    e = motor_dc_stop(m, MOTOR_DC_COAST);
    if (e != DZ_OK) m->ready = false;
    return e;
}

dz_err_t motor_dc_set(motor_dc_t *m, float cmd)
{
    if (m == 0 || !m->ready) return DZ_ESTATE;
    const motor_dc_cfg_t *c = &m->cfg;
    if (!md_finite(cmd)) cmd = 0.0f;
    if (cmd > 1.0f) cmd = 1.0f;
    if (cmd < -1.0f) cmd = -1.0f;
    m->cmd = cmd;

    float phys = c->invert ? -cmd : cmd;
    int dir = phys > 0.0f ? 1 : (phys < 0.0f ? -1 : 0);
    float mag = phys < 0.0f ? -phys : phys;
    float duty = 0.0f;
    if (dir != 0) duty = c->deadband + mag * (c->max_duty - c->deadband);

    dz_err_t e;
    if (dir != m->dir) {
        e = pal_pwm_set_duty(c->pwm, 0);   /* 换向前先关 PWM */
        if (e != DZ_OK) return e;
        e = md_write_dir(c, dir);
        if (e != DZ_OK) return e;
        m->dir = (int8_t)dir;
    }
    return pal_pwm_set_duty(c->pwm, md_duty_raw(duty));
}

dz_err_t motor_dc_stop(motor_dc_t *m, motor_dc_stop_t how)
{
    if (m == 0 || !m->ready) return DZ_ESTATE;
    dz_err_t e = pal_pwm_set_duty(m->cfg.pwm, 0);
    if (e != DZ_OK) return e;
    m->cmd = 0.0f;
    m->dir = 0;
    if (how == MOTOR_DC_BRAKE && m->cfg.mode == MOTOR_DC_PWM_IN1_IN2) {
        e = md_write_dir(&m->cfg, 2);
        if (e != DZ_OK) return e;
        /* TB6612 真值表：IN1=IN2=H 时无论 PWM 电平都是短接制动。
         * 换用其他驱动芯片时请核对其真值表，必要时新增模式而不是改这里。 */
        return DZ_OK;
    }
    return md_write_dir(&m->cfg, 0);
}

float motor_dc_get_cmd(const motor_dc_t *m) { return m ? m->cmd : 0.0f; }

dz_err_t motor_dc_selftest(motor_dc_t *m, float test_duty, uint32_t hold_ms)
{
    if (m == 0 || !m->ready) return DZ_ESTATE;
    if (!md_finite(test_duty) || test_duty <= 0.0f || test_duty > 1.0f) return DZ_EINVAL;
    dz_err_t e = motor_dc_set(m, test_duty);
    if (e != DZ_OK) goto out;
    pal_delay_ms(hold_ms);
    e = motor_dc_set(m, -test_duty);
    if (e != DZ_OK) goto out;
    pal_delay_ms(hold_ms);
out:
    if (motor_dc_stop(m, MOTOR_DC_COAST) != DZ_OK && e == DZ_OK) e = DZ_EIO;
    return e;
}
