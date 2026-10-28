/**
 * 子系统 ball：根据视觉坐标用 PD 控制两路舵机，把钢珠稳在目标点；可选底盘加速度前馈。
 * 读：vision_out, coord, chassis_out   写：ball_out
 * 视觉丢失时舵机保持上一次输出（不回中，避免钢珠被甩出），超过超时由 vision 置 valid=false。
 */
#include "project_gen.h"
#include "pid.h"

static pid_ctrl_t s_x, s_y;

static uint16_t to_us(const params_t *p, float u)
{
    float v = (float)p->servo_mid_us + u;
    float lo = (float)(p->servo_mid_us - p->servo_span_us), hi = (float)(p->servo_mid_us + p->servo_span_us);
    if (v < lo) v = lo;
    if (v > hi) v = hi;
    return (uint16_t)(v + 0.5f);
}

static dz_err_t ball_init(void *state, const void *params)
{
    shared_state_t *st = state; const params_t *p = params;
    pid_cfg_t c = pid_cfg_default(PERIOD_MS_BALL * 1e-3f);
    c.kp = p->ball_kp; c.kd = p->ball_kd; c.d_tau_s = 0.03f;
    c.out_min = -(float)p->servo_span_us; c.out_max = (float)p->servo_span_us;
    c.i_min = c.i_max = 0.0f;
    dz_err_t e = pid_init(&s_x, &c);
    if (e == DZ_OK) e = pid_init(&s_y, &c);
    st->ball_out.servo_x_us = st->ball_out.servo_y_us = p->servo_mid_us;
    return e;
}

static void ball_step(void *state, const void *params, uint32_t now_ms)
{
    shared_state_t *st = state; const params_t *p = params; (void)now_ms;
    if (s_x.cfg.kp != p->ball_kp || s_x.cfg.kd != p->ball_kd) {
        pid_set_gains(&s_x, p->ball_kp, 0, p->ball_kd); pid_set_gains(&s_y, p->ball_kp, 0, p->ball_kd);
    }
    if (!st->vision_out.valid) return;                         /* 保持上次输出 */
    /* 目标 - 测量 > 0 时舵机正向偏转；方向与机械安装有关，若反了把 ball_kp 对应轴改成反向安装或交换 */
    float ux = pid_update(&s_x, st->coord.ball_sp_x_mm, st->vision_out.x_mm);
    float uy = pid_update(&s_y, st->coord.ball_sp_y_mm, st->vision_out.y_mm);
    ux += p->ball_ff * st->chassis_out.accel_rps2;             /* 跨子系统前馈：只读 chassis_out */
    st->ball_out.servo_x_us = to_us(p, ux);
    st->ball_out.servo_y_us = to_us(p, uy);
}

static void ball_on_mode(void *state, subsys_mode_t mode)
{
    shared_state_t *st = state;
    if (mode != SUBSYS_MODE_RUN) {
        pid_reset(&s_x); pid_reset(&s_y);
        /* 待机/急停：舵机回中（安全姿态由题目决定，必要时改这里） */
        st->ball_out.servo_x_us = st->ball_out.servo_y_us = 1500;
    }
}

const subsys_t SUBSYS_BALL = { "ball", PERIOD_MS_BALL, false, ball_init, ball_step, ball_on_mode, 0 };
