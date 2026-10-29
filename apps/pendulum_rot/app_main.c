/**
 * @file app_main.c
 * @brief 旋转倒立摆平衡：1 kHz 读摆臂 / 摆杆编码器 → 状态反馈 → 占空比。倒下（|α| > fall_deg）输出归零，
 *        摆杆回到 ±3° 内自动重新投入。只用逻辑资源名；LINK 交给 link_app.h。起摆（能量法）未实现。
 */
#include "board_gen.h"
#include "app.h"
#include "motor_dc.h"
#include "encoder.h"
#include "lpf1.h"
#include "link_app.h"
#include <math.h>

#define CTRL_PERIOD_US 1000u
#define ARM_CPR  1560.0f    /* 【未验证】摆臂电机输出轴每转计数 */
#define PEND_CPR 2400.0f    /* 【未验证】摆杆编码器（600 线 ×4） */
#define DEG2RAD 0.017453293f

static motor_dc_t s_m;
static encoder_t s_ea, s_ep;
static link_app_t L;
static volatile float s_arm, s_pend, s_u;
static volatile uint8_t s_mode;

static void ctrl_isr(void *ctx)
{
    (void)ctx;
    (void)encoder_update(&s_ea); (void)encoder_update(&s_ep);
    const float th = (float)s_ea.total * (6.2831853f / ARM_CPR), al = (float)s_ep.total * (6.2831853f / PEND_CPR);
    const float thd = encoder_speed_rps(&s_ea) * 6.2831853f, ald = encoder_speed_rps(&s_ep) * 6.2831853f;
    s_arm = th / DEG2RAD; s_pend = al / DEG2RAD;
    if (L.estop) { s_mode = 2; s_u = 0; motor_dc_stop(&s_m, MOTOR_DC_BRAKE); return; }
    if (fabsf(s_pend) > g_link_params.fall_deg) s_mode = 0;
    else if (s_mode != 1 && fabsf(s_pend) < 3.0f) s_mode = 1;   /* 扶正后重新投入 */
    if (s_mode != 1) { s_u = 0; motor_dc_stop(&s_m, MOTOR_DC_COAST); return; }
    float u = g_link_params.k_al * al + g_link_params.k_ald * ald
            + g_link_params.k_th * (th - L.sp[0] * DEG2RAD) + g_link_params.k_thd * thd;
    if (u > 1.0f) u = 1.0f;
    if (u < -1.0f) u = -1.0f;
    s_u = u;
    (void)motor_dc_set(&s_m, u);
}

static dz_err_t enc(encoder_t *e, pal_id_t id, float cpr)
{
    encoder_cfg_t ec = encoder_cfg_default();
    ec.enc = id; ec.counts_per_rev = cpr; ec.dt_s = CTRL_PERIOD_US * 1e-6f; ec.speed_lpf_hz = 80.0f; ec.window_n = 4;
    return encoder_init(e, &ec);
}

dz_err_t app_init(void)
{
    dz_err_t e;
    motor_dc_cfg_t mc = motor_dc_cfg_default();
    mc.mode = MOTOR_DC_PWM_IN1_IN2; mc.pwm = RES_PWM_MOTOR_A; mc.in1 = RES_GPIO_MOTOR_A_IN1; mc.in2 = RES_GPIO_MOTOR_A_IN2; mc.max_duty = 1.0f;
    if ((e = motor_dc_init(&s_m, &mc)) != DZ_OK) return e;
    if ((e = enc(&s_ea, RES_ENCODER_MOTOR_A, ARM_CPR)) != DZ_OK) return e;
    if ((e = enc(&s_ep, RES_ENCODER_MOTOR_B, PEND_CPR)) != DZ_OK) return e;
    link_app_init(&L, 0, 0);
    return pal_timer_start(RES_TIMER_CTRL, CTRL_PERIOD_US, ctrl_isr, 0);
}

void app_loop(void)
{
    uint32_t now = pal_millis();
    if (!link_app_poll(&L, now)) return;
    link_telem_t t = { 0 };
    uint32_t st = pal_irq_save();
    t.t_ms = now; t.sp_arm_deg = L.sp[0]; t.arm_deg = s_arm; t.pend_deg = s_pend; t.u = s_u; t.mode = s_mode;
    pal_irq_restore(st);
    link_app_send_telem(&L, &t);
}
