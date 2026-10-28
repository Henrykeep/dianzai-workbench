#include "tt.h"
#include "pid.h"

static pid_cfg_t base(void)
{
    pid_cfg_t c = pid_cfg_default(0.001f);
    c.kp = 1.0f; c.ki = 0.0f; c.kd = 0.0f;
    return c;
}

TEST(pid_cfg_rejects_bad)
{
    pid_cfg_t c;
    c = base(); c.kp = -1;        CHECK(pid_cfg_check(&c) == DZ_EINVAL);
    c = base(); c.dt_s = 0;       CHECK(pid_cfg_check(&c) == DZ_EINVAL);
    c = base(); c.out_min = 1;    CHECK(pid_cfg_check(&c) == DZ_EINVAL);
    c = base(); c.i_min = 2; c.i_max = 1; CHECK(pid_cfg_check(&c) == DZ_EINVAL);
    c = base(); c.ki = NAN;       CHECK(pid_cfg_check(&c) == DZ_EINVAL);
    c = base(); c.d_tau_s = -1;   CHECK(pid_cfg_check(&c) == DZ_EINVAL);
    c = base();                   CHECK(pid_cfg_check(&c) == DZ_OK);
    CHECK(pid_cfg_check(0) == DZ_EINVAL);
    pid_ctrl_t p = {0};
    CHECK(pid_update(&p, 1, 0) == 0.0f);              /* 未初始化不输出 */
    CHECK(pid_update(0, 1, 0) == 0.0f);
}

TEST(pid_p_and_clamp)
{
    pid_ctrl_t p; pid_cfg_t c = base();
    pid_init(&p, &c);
    CHECK_NEAR(pid_update(&p, 0.5f, 0.0f), 0.5f, 1e-6);
    CHECK_NEAR(pid_update(&p, 5.0f, 0.0f), 1.0f, 1e-6);   /* 输出限幅 */
    CHECK_NEAR(pid_update(&p, -5.0f, 0.0f), -1.0f, 1e-6);
}

TEST(pid_integral_clamp_and_antiwindup)
{
    pid_ctrl_t p; pid_cfg_t c = base();
    c.kp = 0.0f; c.ki = 10.0f; c.i_min = -0.5f; c.i_max = 0.5f;
    pid_init(&p, &c);
    for (int i = 0; i < 5000; i++) pid_update(&p, 1.0f, 0.0f);
    CHECK_NEAR(p.integ, 0.5f, 1e-6);                      /* 积分贡献被限在 i_max */
    /* 抗饱和：kp 很大使输出饱和时积分不应继续增长 */
    c.kp = 10.0f; c.i_max = 1.0f; c.i_min = -1.0f;
    pid_init(&p, &c);
    for (int i = 0; i < 5000; i++) pid_update(&p, 1.0f, 0.0f);
    CHECK(p.integ < 0.05f);
    /* 误差反号后应立即离开饱和 */
    float u = pid_update(&p, -1.0f, 0.0f);
    CHECK(u < 0.0f);
}

TEST(pid_integral_separation)
{
    pid_ctrl_t p; pid_cfg_t c = base();
    c.kp = 0.0f; c.ki = 1.0f; c.i_sep = 0.5f;
    pid_init(&p, &c);
    for (int i = 0; i < 100; i++) pid_update(&p, 1.0f, 0.0f);
    CHECK_NEAR(p.integ, 0.0f, 1e-9);
    for (int i = 0; i < 100; i++) pid_update(&p, 0.2f, 0.0f);
    CHECK(p.integ > 0.0f);
}

TEST(pid_d_on_measurement_no_kick)
{
    pid_ctrl_t p; pid_cfg_t c = base();
    c.kp = 0.0f; c.kd = 0.01f; c.d_mode = PID_D_ON_MEASUREMENT;
    pid_init(&p, &c);
    pid_update(&p, 0.0f, 0.0f);
    CHECK_NEAR(pid_update(&p, 1.0f, 0.0f), 0.0f, 1e-9);    /* 设定值阶跃不产生微分冲击 */
    CHECK(pid_update(&p, 1.0f, 0.01f) < 0.0f);             /* 测量上升 -> 负微分 */
    c.d_mode = PID_D_ON_ERROR;
    pid_init(&p, &c);
    pid_update(&p, 0.0f, 0.0f);
    CHECK(pid_update(&p, 1.0f, 0.0f) > 0.5f);              /* 对误差微分则有冲击（对比项） */
}

TEST(pid_d_filter_reduces_noise)
{
    pid_ctrl_t raw, filt; pid_cfg_t c = base();
    c.kp = 0.0f; c.kd = 0.001f; c.out_min = -100; c.out_max = 100;
    pid_init(&raw, &c);
    c.d_tau_s = 0.01f;
    pid_init(&filt, &c);
    double e_raw = 0, e_f = 0;
    for (int i = 0; i < 1000; i++) {
        float n = (i & 1) ? 0.01f : -0.01f;
        float a = pid_update(&raw, 0, n), b = pid_update(&filt, 0, n);
        if (i > 100) { e_raw += a * a; e_f += b * b; }
    }
    CHECK(e_f < e_raw * 0.1);
}

TEST(pid_rate_limit)
{
    pid_ctrl_t p; pid_cfg_t c = base();
    c.kp = 100.0f; c.out_rate_max = 10.0f;              /* 10/s -> 每 1ms 最多 0.01 */
    pid_init(&p, &c);
    CHECK_NEAR(pid_update(&p, 1.0f, 0.0f), 0.01f, 1e-5);
    CHECK_NEAR(pid_update(&p, 1.0f, 0.0f), 0.02f, 1e-5);
}

TEST(pid_nan_holds_output)
{
    pid_ctrl_t p; pid_cfg_t c = base();
    pid_init(&p, &c);
    float u = pid_update(&p, 0.3f, 0.0f);
    CHECK_NEAR(pid_update(&p, 0.3f, NAN), u, 1e-9);
    CHECK_NEAR(pid_update(&p, NAN, 0.0f), u, 1e-9);
    CHECK(p.nan_count == 2);
}

TEST(pid_bumpless_gain_change_and_reset_to)
{
    pid_ctrl_t p; pid_cfg_t c = base();
    c.kp = 0.0f; c.ki = 1.0f;
    pid_init(&p, &c);
    for (int i = 0; i < 300; i++) pid_update(&p, 1.0f, 0.5f);
    float before = pid_output(&p);
    CHECK(pid_set_gains(&p, 0.0f, 5.0f, 0.0f) == DZ_OK);
    float after = pid_update(&p, 1.0f, 1.0f);              /* 误差为 0 时输出不应跳变 */
    CHECK_NEAR(after, before, 1e-6);
    CHECK(pid_set_gains(&p, -1.0f, 0, 0) == DZ_EINVAL);
    pid_reset_to(&p, 0.4f);
    CHECK_NEAR(pid_update(&p, 1.0f, 1.0f), 0.4f, 1e-6);
    pid_reset(&p);
    CHECK_NEAR(pid_update(&p, 1.0f, 1.0f), 0.0f, 1e-6);
}

TEST(pid_incremental_basic)
{
    pid_inc_t p; pid_cfg_t c = base();
    c.kp = 0.5f; c.ki = 2.0f;
    CHECK(pid_inc_init(&p, &c) == DZ_OK);
    float u = 0;
    for (int i = 0; i < 100; i++) u = pid_inc_update(&p, 1.0f, 0.0f);
    CHECK(u > 0.0f && u <= 1.0f);
    for (int i = 0; i < 5000; i++) u = pid_inc_update(&p, 1.0f, 0.0f);
    CHECK_NEAR(u, 1.0f, 1e-6);                                /* 输出限幅 */
    u = pid_inc_update(&p, -1.0f, 0.0f);
    CHECK(u < 1.0f);                                          /* 增量式天然无积分饱和 */
    CHECK_NEAR(pid_inc_update(&p, NAN, 0), u, 1e-9);
}

TEST(pid_cascade_dt_check)
{
    pid_cascade_t cc; pid_cfg_t in = base(), out = base();
    out.dt_s = 0.005f;
    CHECK(pid_cascade_init(&cc, &out, &in, 4) == DZ_EINVAL); /* 5 ms != 4×1 ms */
    CHECK(pid_cascade_init(&cc, &out, &in, 5) == DZ_OK);
    CHECK(pid_cascade_init(&cc, &out, &in, 0) == DZ_EINVAL);
}

TEST(pid_selftest_ok) { CHECK(pid_selftest() == DZ_OK); }

void suite_pid(void)
{
    RUN(pid_cfg_rejects_bad); RUN(pid_p_and_clamp); RUN(pid_integral_clamp_and_antiwindup);
    RUN(pid_integral_separation); RUN(pid_d_on_measurement_no_kick); RUN(pid_d_filter_reduces_noise);
    RUN(pid_rate_limit); RUN(pid_nan_holds_output); RUN(pid_bumpless_gain_change_and_reset_to);
    RUN(pid_incremental_basic); RUN(pid_cascade_dt_check); RUN(pid_selftest_ok);
}
