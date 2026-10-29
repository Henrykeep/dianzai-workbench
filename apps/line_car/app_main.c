/**
 * @file app_main.c
 * @brief 循线小车：1 kHz 轮速 PI（中断）；主循环 5 ms 读 8 路灰度 → 线位置 PD → 两轮目标速度。
 *        丢线走 algo/line_obs：连续 3 拍没线才算丢 → 朝最后看到线的一侧原地慢转找线（正前方突然丢的就原地左右扫、逐段加大），
 *        连续 10 拍看到才算找回；找 lost_ms 仍没找到 → FAIL 停车（'R' 或 'L' 复位观测器）。每次丢线/失败记黑匣子（BB_EV_LINE_LOST）。
 *        线位置设定 line_sp_mm 走 LINK DATA id=1（f32 mm，默认 0 = 线在正中），工作台阶跃实验改它。
 */
#include "board_gen.h"
#include "app.h"
#include "pid.h"
#include "motor_dc.h"
#include "encoder.h"
#include "line_sensor.h"
#include "link_app.h"
#include "line_obs.h"
#include "blackbox.h"

#define CTRL_PERIOD_US 1000u
#define COUNTS_PER_REV 1560.0f   /* 【未验证】 */

typedef struct { motor_dc_t m; encoder_t e; pid_ctrl_t pid; } wheel_t;
static wheel_t s_w[2];
static line_sensor_t s_line;
static link_app_t L;
static volatile float s_sp[2];
static volatile bool s_dirty = true;
static float s_pos, s_last_pos;
static uint8_t s_mode;                       /* 遥测 mode：0 LOST(=FAIL 停车) 1 RUNNING 2 ESTOP 3 SEARCH */
static line_obs_t s_obs;
static bb_t s_bb;
static bb_rec_t s_bb_ring[16];

static void on_cmd(uint8_t c, uint8_t n) { (void)n; if (c == 'L') line_obs_reset(&s_obs); }

static void apply_params(void) { s_dirty = true; }

static void ctrl_isr(void *ctx)
{
    static uint32_t last_us;
    uint32_t now = pal_micros();
    float dt = (float)(now - last_us) * 1e-6f;
    (void)ctx;
    last_us = now;
    for (unsigned i = 0; i < 2; i++) {
        wheel_t *w = &s_w[i];
        (void)pid_check_gap(&w->pid, dt);
        if (s_dirty) (void)pid_set_gains(&w->pid, g_link_params.kp, g_link_params.ki, 0.0f);
        (void)encoder_update(&w->e);
        if (L.estop || (s_mode != 1 && s_mode != 3)) { motor_dc_stop(&w->m, MOTOR_DC_BRAKE); pid_reset(&w->pid); continue; }
        (void)motor_dc_set(&w->m, pid_update(&w->pid, s_sp[i], encoder_speed_rps(&w->e)));
    }
    s_dirty = false;
}

static dz_err_t wheel_init(wheel_t *w, pal_id_t pwm, pal_id_t in1, pal_id_t in2, pal_id_t enc)
{
    dz_err_t e;
    motor_dc_cfg_t mc = motor_dc_cfg_default();
    mc.mode = MOTOR_DC_PWM_IN1_IN2; mc.pwm = pwm; mc.in1 = in1; mc.in2 = in2; mc.max_duty = 0.95f;
    if ((e = motor_dc_init(&w->m, &mc)) != DZ_OK) return e;
    encoder_cfg_t ec = encoder_cfg_default();
    ec.enc = enc; ec.counts_per_rev = COUNTS_PER_REV; ec.dt_s = CTRL_PERIOD_US * 1e-6f; ec.speed_lpf_hz = 50.0f;
    if ((e = encoder_init(&w->e, &ec)) != DZ_OK) return e;
    pid_cfg_t pc = pid_cfg_default(CTRL_PERIOD_US * 1e-6f);
    pc.kp = g_link_params.kp; pc.ki = g_link_params.ki; pc.out_min = -1; pc.out_max = 1; pc.i_min = -1; pc.i_max = 1;
    return pid_init(&w->pid, &pc);
}

dz_err_t app_init(void)
{
    static const pal_id_t ids[8] = { RES_GPIO_LINE0, RES_GPIO_LINE1, RES_GPIO_LINE2, RES_GPIO_LINE3,
                                     RES_GPIO_LINE4, RES_GPIO_LINE5, RES_GPIO_LINE6, RES_GPIO_LINE7 };
    dz_err_t e;
    if ((e = wheel_init(&s_w[0], RES_PWM_MOTOR_A, RES_GPIO_MOTOR_A_IN1, RES_GPIO_MOTOR_A_IN2, RES_ENCODER_MOTOR_A)) != DZ_OK) return e;
    if ((e = wheel_init(&s_w[1], RES_PWM_MOTOR_B, RES_GPIO_MOTOR_B_IN1, RES_GPIO_MOTOR_B_IN2, RES_ENCODER_MOTOR_B)) != DZ_OK) return e;
    line_cfg_t lc = line_cfg_default();
    lc.n = 8; lc.pitch_mm = 12.0f;
    for (unsigned i = 0; i < 8; i++) lc.ids[i] = ids[i];
    if ((e = line_init(&s_line, &lc)) != DZ_OK) return e;
    line_obs_cfg_t oc = line_obs_cfg_default();
    oc.center_band = 6.0f;                                        /* 半个灰度间距内算“正前方丢的” */
    if ((e = line_obs_init(&s_obs, &oc)) != DZ_OK) return e;
    (void)bb_init(&s_bb, s_bb_ring, (uint16_t)(sizeof s_bb_ring / sizeof s_bb_ring[0]), NULL);
    bb_log(&s_bb, pal_millis(), BB_EV_RESET, 0, 0.0f, 0.0f);
    link_app_init(&L, apply_params, on_cmd);
    L.bb = &s_bb;
    return pal_timer_start(RES_TIMER_CTRL, CTRL_PERIOD_US, ctrl_isr, 0);
}

void app_loop(void)
{
    static uint32_t last_ctl;
    static bool was_estop;
    uint32_t now = pal_millis();
    if (was_estop && !L.estop && s_obs.st == LINE_OBS_FAIL) line_obs_reset(&s_obs);   /* 'R' 解除急停顺带复位找线失败 */
    was_estop = L.estop;
    if (now - last_ctl >= 5u) {                                   /* 外环 200 Hz */
        line_result_t r;
        float dt = (float)(now - last_ctl) * 1e-3f;
        last_ctl = now;
        if (line_read(&s_line, &r) == DZ_OK) {
            bool seen = !(r.flags & LINE_F_LOST);
            line_obs_state_t os0 = s_obs.st, os = line_obs_update(&s_obs, seen, r.pos_mm, (r.flags & LINE_F_CROSS) != 0u, now);
            if (line_obs_just_lost(&s_obs)) bb_log(&s_bb, now, BB_EV_LINE_LOST, (uint16_t)LINE_OBS_LOST, s_pos, (float)s_obs.lost_count);
            if (os == LINE_OBS_FAIL && os0 != LINE_OBS_FAIL) bb_log(&s_bb, now, BB_EV_LINE_LOST, (uint16_t)LINE_OBS_FAIL, s_pos, (float)s_obs.lost_count);
            float va, vb;
            if (os == LINE_OBS_FAIL) { s_mode = 0u; va = vb = 0.0f; }
            else if (os == LINE_OBS_LOST) {                         /* 找线：朝丢线一侧原地转；方向不定就慢速直行 */
                float vs = g_link_params.v_search;
                int8_t d = line_obs_dir(&s_obs);
                s_mode = 3u;
                static uint32_t seg_t0; static uint8_t seg_k; static int8_t sweep;
                if (line_obs_just_lost(&s_obs)) { seg_t0 = now; seg_k = 1u; sweep = 1; }
                if (d == 0) {                                       /* 正前方突然丢（被撞偏）：原地左右扫，幅度逐段加大（300·k ms） */
                    if ((uint32_t)(now - seg_t0) >= 300u * seg_k) { seg_t0 = now; seg_k = (uint8_t)(seg_k + (seg_k < 40u)); sweep = (int8_t)-sweep; }
                    d = sweep;
                }
                s_pos = r.pos_mm;
                va = (float)d * vs; vb = -(float)d * vs;            /* d=+1 线在右 → 左轮正转右轮反转 → 原地右转 */
            } else {
                s_mode = 1u;
                s_pos = r.pos_mm;
                float err = s_pos - L.sp[0], dw = g_link_params.kp_line * err + g_link_params.kd_line * (s_pos - s_last_pos) / dt;
                s_last_pos = s_pos;
                va = g_link_params.v_base + dw;                     /* 线在右（pos>0）→ 左轮(A)快 → 右转 */
                vb = g_link_params.v_base - dw;
            }
            uint32_t st = pal_irq_save();
            s_sp[0] = va; s_sp[1] = vb;
            pal_irq_restore(st);
        }
    }
    if (!link_app_poll(&L, now)) return;
    link_telem_t t = { 0 };
    uint32_t st = pal_irq_save();
    t.t_ms = now; t.line_sp_mm = L.sp[0]; t.line_mm = s_pos;
    t.sp_a = s_sp[0]; t.sp_b = s_sp[1]; t.spd_a = encoder_speed_rps(&s_w[0].e); t.spd_b = encoder_speed_rps(&s_w[1].e);
    pal_irq_restore(st);
    t.mode = L.estop ? 2u : s_mode;
    link_app_send_telem(&L, &t);
}
