/**
 * @file app_main.c
 * @brief 电机位置环：1 kHz 读编码器累计角度 → PID → 占空比（带死区补偿）。只用逻辑资源名。
 *        LINK 收发、急停、心跳交给 link_app.h。
 */
#include "board_gen.h"
#include "app.h"
#include "pid.h"
#include "motor_dc.h"
#include "encoder.h"
#include "link_app.h"
#include <math.h>

#define CTRL_PERIOD_US 1000u
#define COUNTS_PER_REV 1560.0f    /* 【未验证】按电机型号改；仿真同值 */

static motor_dc_t s_m;
static encoder_t s_e;
static pid_ctrl_t s_pid;
static link_app_t L;
static volatile bool s_dirty = true;
static volatile float s_pos_deg, s_u;

static void apply_params(void) { s_dirty = true; }

static void ctrl_isr(void *ctx)
{
    static uint32_t last_us;
    uint32_t now = pal_micros();
    (void)ctx;
    (void)pid_check_gap(&s_pid, (float)(now - last_us) * 1e-6f);
    last_us = now;
    if (s_dirty) {
        (void)pid_set_gains(&s_pid, g_link_params.kp, g_link_params.ki, g_link_params.kd);
        s_pid.cfg.out_min = -g_link_params.max_u; s_pid.cfg.out_max = g_link_params.max_u;
        s_dirty = false;
    }
    (void)encoder_update(&s_e);
    s_pos_deg = (float)s_e.total * (360.0f / COUNTS_PER_REV);
    if (L.estop) { motor_dc_stop(&s_m, MOTOR_DC_BRAKE); pid_reset(&s_pid); s_u = 0; return; }
    float u = pid_update(&s_pid, L.sp[0], s_pos_deg);
    if (fabsf(u) > 1e-3f) u += u > 0 ? g_link_params.deadband : -g_link_params.deadband;   /* 静摩擦补偿 */
    if (u > g_link_params.max_u) u = g_link_params.max_u;
    if (u < -g_link_params.max_u) u = -g_link_params.max_u;
    s_u = u;
    (void)motor_dc_set(&s_m, u);
}

dz_err_t app_init(void)
{
    dz_err_t e;
    motor_dc_cfg_t mc = motor_dc_cfg_default();
    mc.mode = MOTOR_DC_PWM_IN1_IN2; mc.pwm = RES_PWM_MOTOR_A; mc.in1 = RES_GPIO_MOTOR_A_IN1; mc.in2 = RES_GPIO_MOTOR_A_IN2; mc.max_duty = 1.0f;
    if ((e = motor_dc_init(&s_m, &mc)) != DZ_OK) return e;
    encoder_cfg_t ec = encoder_cfg_default();
    ec.enc = RES_ENCODER_MOTOR_A; ec.counts_per_rev = COUNTS_PER_REV; ec.dt_s = CTRL_PERIOD_US * 1e-6f;
    if ((e = encoder_init(&s_e, &ec)) != DZ_OK) return e;
    pid_cfg_t pc = pid_cfg_default(CTRL_PERIOD_US * 1e-6f);
    pc.kp = g_link_params.kp; pc.ki = g_link_params.ki; pc.kd = g_link_params.kd;
    pc.out_min = -1.0f; pc.out_max = 1.0f; pc.i_min = -0.5f; pc.i_max = 0.5f;
    if ((e = pid_init(&s_pid, &pc)) != DZ_OK) return e;
    link_app_init(&L, apply_params, 0);
    return pal_timer_start(RES_TIMER_CTRL, CTRL_PERIOD_US, ctrl_isr, 0);
}

void app_loop(void)
{
    uint32_t now = pal_millis();
    if (!link_app_poll(&L, now)) return;
    link_telem_t t = { 0 };
    uint32_t st = pal_irq_save();
    t.t_ms = now; t.sp_deg = L.sp[0]; t.pos_deg = s_pos_deg; t.u = s_u;
    pal_irq_restore(st);
    t.run = L.estop ? 2u : 1u;
    link_app_send_telem(&L, &t);
}
