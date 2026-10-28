#include "drive_plan.h"

#define PERIOD_MS 10u
#define PI_F 3.14159265f

static float ramp(float cur, float target, float step)
{
    if (target > cur + step) return cur + step;
    if (target < cur - step) return cur - step;
    return target;
}

static float clampf(float x, float lim) { return x > lim ? lim : (x < -lim ? -lim : x); }

static dz_err_t dp_init(void *state, const void *params)
{
    car_state_t *s = state;
    const drive_params_t *p = params;
    if (!s || !p || p->wheel_diam_m <= 0.0f || p->track_m <= 0.0f || p->max_rps <= 0.0f) return DZ_EINVAL;
    s->sp_a_rps = s->sp_b_rps = 0.0f;
    s->timed_out = true;
    return DZ_OK;
}

static void dp_step(void *state, const void *params, uint32_t now_ms)
{
    car_state_t *s = state;
    const drive_params_t *p = params;
    s->timed_out = (now_ms - s->cmd_ms) > p->cmd_timeout_ms;
    float ta = 0.0f, tb = 0.0f;
    if (!s->timed_out) {
        /* 差速运动学：轮缘线速度 = v ∓ w·轮距/2，再换算成转/秒 */
        float circ = PI_F * p->wheel_diam_m;
        ta = clampf((s->cmd_v_mps - s->cmd_w_rps * p->track_m * 0.5f) / circ, p->max_rps);
        tb = clampf((s->cmd_v_mps + s->cmd_w_rps * p->track_m * 0.5f) / circ, p->max_rps);
    }
    float step = p->accel_rps2 * (float)PERIOD_MS * 1e-3f;
    s->sp_a_rps = ramp(s->sp_a_rps, ta, step);
    s->sp_b_rps = ramp(s->sp_b_rps, tb, step);
}

static void dp_on_mode(void *state, subsys_mode_t mode)
{
    car_state_t *s = state;
    if (mode != SUBSYS_MODE_RUN) s->sp_a_rps = s->sp_b_rps = 0.0f;
}

static dz_err_t dp_selftest(void)
{
    car_state_t s = {0};
    const drive_params_t p = { 0.065f, 0.15f, 5.0f, 1000.0f, 200u };
    if (dp_init(&s, &p) != DZ_OK) return DZ_EIO;
    s.cmd_v_mps = 0.2f; s.cmd_w_rps = 0.0f; s.cmd_ms = 1000u;
    dp_step(&s, &p, 1010u);
    if (s.timed_out || s.sp_a_rps <= 0.0f || s.sp_a_rps != s.sp_b_rps) return DZ_EIO;   /* 直行两轮相同 */
    dp_step(&s, &p, 1500u);
    if (!s.timed_out || s.sp_a_rps != 0.0f) return DZ_EIO;                              /* 超时必须停 */
    return DZ_OK;
}

const subsys_t g_drive_plan = {
    .name = "drive_plan", .period_ms = PERIOD_MS, .run_always = false,
    .init = dp_init, .step = dp_step, .on_mode = dp_on_mode, .selftest = dp_selftest,
};
