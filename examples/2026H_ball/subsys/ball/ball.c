/**
 * 子系统 ball：单轴球杆。视觉样本 → firmware/algo/ball_beam（α-β + 超前 + 串级 + 条件积分）→ 摆杆角，
 * 叠加加速度前馈（编码器/IMU 可选，死区 + 失效保护），换算成 QD4310 绝对角并做机械硬限位（限位与零点无关、始终有效，沿用 P2 的做法）。
 * 读：vision_out, coord, chassis_out   写：beam_out
 */
#include <math.h>
#include <string.h>
#include "project_gen.h"
#include "ball_beam.h"

#define RAD2DEG 57.29578f
#define G_MPS2  9.80665f

static ball_beam_t s_bb;

static ball_beam_cfg_t cfg_from(const params_t *p)
{
    ball_beam_cfg_t c;
    c.alpha = p->bb_alpha; c.beta = p->bb_beta; c.lead_s = p->bb_lead_s;
    c.pos_k = p->pos_k; c.vel_max = p->vel_max; c.vel_k = p->vel_k;
    c.ki = p->ball_ki; c.i_zone = p->i_zone_px; c.i_max = p->i_max_deg; c.i_decay = p->i_decay;
    c.angle_max = p->angle_max_deg; c.rate_max = p->rate_max_dps;
    c.hold_ms = p->hold_ms; c.timeout_ms = p->vision_timeout_ms; c.dir = p->beam_dir;
    c.est_mode = p->bb_est_mode; c.est_lpf = 0.3f; c.loop_mode = p->bb_loop_mode;
    c.stic_deg = p->stic_deg; c.stic_vel = p->stic_vel; c.stic_e = p->stic_e;
    memset(c.bal_x, 0, sizeof c.bal_x); memset(c.bal_deg, 0, sizeof c.bal_deg);
    c.bal_n = p->bal_span_px > 0.0f ? 3u : 0u;
    c.bal_x[0] = -p->bal_span_px; c.bal_x[1] = 0.0f; c.bal_x[2] = p->bal_span_px;
    c.bal_deg[0] = p->bal_l_deg; c.bal_deg[1] = p->bal_c_deg; c.bal_deg[2] = p->bal_r_deg;
    return c;
}

static float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

/* 加速度前馈：来源可选（编码器差分 / IMU），带死区和失效保护。任何异常都让前馈变成 0（退回纯反馈），不会锁死。 */
static float accel_ff(const shared_state_t *st, const params_t *p, uint32_t now_ms)
{
    float a;
    if (p->ff_gain == 0.0f) return 0.0f;
    if (p->ff_src == 1u) {
        if (!st->io_in.imu_ok || (uint32_t)(now_ms - st->io_in.imu_rx_ms) > p->imu_timeout_ms) return 0.0f;
        a = st->io_in.imu_ax_mps2;
    } else {
        a = st->chassis_out.accel_mps2;
    }
    if (!(a == a) || fabsf(a) > p->ff_fail_mps2) return 0.0f;           /* NaN / 读数异常 */
    if (fabsf(a) < p->ff_dead_mps2) return 0.0f;                        /* 死区 */
    a -= a > 0.0f ? p->ff_dead_mps2 : -p->ff_dead_mps2;                 /* 死区边沿连续，不跳变 */
    return clampf(a / G_MPS2 * RAD2DEG * p->ff_gain, -p->ff_max_deg, p->ff_max_deg);   /* 小角近似 θ≈a/g */
}

static void publish(shared_state_t *st, const params_t *p, float angle)
{
    st->beam_out.angle_deg = angle;
    st->beam_out.target_abs_deg = clampf(p->beam_zero_deg + angle, p->beam_min_deg, p->beam_max_deg);
    st->beam_out.state = (uint8_t)ball_beam_state(&s_bb);
}

static dz_err_t ball_init(void *state, const void *params)
{
    shared_state_t *st = state; const params_t *p = params;
    ball_beam_cfg_t c = cfg_from(p);
    dz_err_t e = ball_beam_init(&s_bb, &c);
    publish(st, p, 0.0f);
    return e;
}

static void ball_step(void *state, const void *params, uint32_t now_ms)
{
    shared_state_t *st = state; const params_t *p = params;
    ball_beam_cfg_t c = cfg_from(p);
    float ff = 0.0f;
    if (memcmp(&c, &s_bb.cfg, sizeof c) != 0) {                /* 切参数档：只换配置，不清状态（无扰） */
        ball_beam_t tmp;
        if (ball_beam_init(&tmp, &c) == DZ_OK) s_bb.cfg = c;
    }
    if (st->vision_out.new_sample) ball_beam_sample(&s_bb, st->vision_out.x_px, st->vision_out.t_ms);
    ff = accel_ff(st, p, now_ms);
    st->beam_out.ff_deg = ff;
    publish(st, p, ball_beam_update(&s_bb, st->coord.ball_sp_px, ff, now_ms, PERIOD_MS_BALL * 1e-3f));
}

static void ball_on_mode(void *state, subsys_mode_t mode)
{
    (void)state;
    if (mode != SUBSYS_MODE_RUN) ball_beam_reset(&s_bb);   /* io 层在非运行态下发零点角/失能，见 io_main.c */
}

const subsys_t SUBSYS_BALL = { "ball", PERIOD_MS_BALL, false, ball_init, ball_step, ball_on_mode, 0 };
