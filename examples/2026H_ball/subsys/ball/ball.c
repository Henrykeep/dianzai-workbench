/**
 * 子系统 ball：单轴球杆。视觉样本 → firmware/algo/ball_beam（α-β + 超前 + 串级 + 条件积分）→ 摆杆角，
 * 叠加加速度前馈（编码器/IMU 可选，死区 + 失效保护），换算成 QD4310 绝对角并做机械硬限位（限位与零点无关、始终有效，沿用 P2 的做法）。
 * 读：vision_out, coord, chassis_out   写：beam_out
 */
#include <math.h>
#include <string.h>
#include "project_gen.h"
#include "ball_beam.h"
#include "accel_ff.h"
#include "slew.h"


static ball_beam_t s_bb;
static slew_t s_sp;          /* 目标斜坡：sp_rate_pxps=0 时直通 */

/* 分段斜坡：离最终目标 band 以内用慢速，否则快速；未就绪时从钢珠当前估计位置起步（无冲击） */
static float sp_ramp(const params_t *p, float sp, float dt)
{
    slew_cfg_t c;
    float r;
    if (!(p->sp_rate_pxps > 0.0f)) { s_sp.ready = false; return sp; }
    if (!s_sp.ready) {
        if (!s_bb.primed) return sp;
        slew_cfg_t z = { 0.0f, 0.0f, SLEW_BY_DIR };
        (void)slew_init(&s_sp, &z, s_bb.x);
    }
    r = (p->sp_slow_pxps > 0.0f && fabsf(sp - s_sp.y) < p->sp_slow_band_px) ? p->sp_slow_pxps : p->sp_rate_pxps;
    c.rise_per_s = c.fall_per_s = r; c.mode = SLEW_BY_DIR;
    s_sp.cfg = c;
    return slew_update(&s_sp, sp, dt);
}

static ball_beam_cfg_t cfg_from(const params_t *p)
{
    ball_beam_cfg_t c;
    c.alpha = p->bb_alpha; c.beta = p->bb_beta; c.lead_s = p->bb_lead_s;
    c.pos_k = p->pos_k; c.vel_max = p->vel_max; c.vel_k = p->vel_k;
    c.ki = p->ball_ki; c.i_zone = p->i_zone_px; c.i_max = p->i_max_deg; c.i_decay = p->i_decay;
    c.angle_max = p->angle_max_deg; c.rate_max = p->rate_max_dps;
    c.hold_ms = p->hold_ms; c.timeout_ms = p->vision_timeout_ms; c.dir = p->beam_dir;
    c.est_mode = p->bb_est_mode; c.est_lpf = 0.3f; c.loop_mode = p->bb_loop_mode;
    c.i_vel = p->i_vel_pxps; c.i_leak = p->i_leak;
    c.stic_deg = p->stic_deg; c.stic_vel = p->stic_vel; c.stic_e = p->stic_e;
    memset(c.bal_x, 0, sizeof c.bal_x); memset(c.bal_deg, 0, sizeof c.bal_deg);
    c.bal_n = p->bal_span_px > 0.0f ? 3u : 0u;
    c.bal_x[0] = -p->bal_span_px; c.bal_x[1] = 0.0f; c.bal_x[2] = p->bal_span_px;
    c.bal_deg[0] = p->bal_l_deg; c.bal_deg[1] = p->bal_c_deg; c.bal_deg[2] = p->bal_r_deg;
    return c;
}

static float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

/* 加速度前馈：来源可选（编码器差分 / IMU）；换算、死区、失效保护在 firmware/algo/accel_ff。任何异常前馈为 0（退回纯反馈）。 */
static float accel_ff(const shared_state_t *st, const params_t *p, uint32_t now_ms)
{
    accel_ff_cfg_t c = { p->ff_gain, p->ff_dead_mps2, p->ff_fail_mps2, p->ff_max_deg };
    if (p->ff_src == 1u) {
        bool ok = st->io_in.imu_ok && (uint32_t)(now_ms - st->io_in.imu_rx_ms) <= p->imu_timeout_ms;
        return accel_ff_deg(&c, st->io_in.imu_ax_mps2, ok);
    }
    return accel_ff_deg(&c, st->chassis_out.accel_mps2, true);
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
    publish(st, p, ball_beam_update(&s_bb, sp_ramp(p, st->coord.ball_sp_px, PERIOD_MS_BALL * 1e-3f), ff, now_ms, PERIOD_MS_BALL * 1e-3f));
}

static void ball_on_mode(void *state, subsys_mode_t mode)
{
    (void)state;
    if (mode != SUBSYS_MODE_RUN) { ball_beam_reset(&s_bb); s_sp.ready = false; }   /* io 层在非运行态下发零点角/失能，见 io_main.c */
}

const subsys_t SUBSYS_BALL = { "ball", PERIOD_MS_BALL, false, ball_init, ball_step, ball_on_mode, 0 };
