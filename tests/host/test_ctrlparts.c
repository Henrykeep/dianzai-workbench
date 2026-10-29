/* G7 控制环常用件：不对称变化率限制、变周期 M/T 测速。 */
#include "tt.h"
#include <math.h>
#include <stdint.h>
#include "slew.h"
#include "mtspeed.h"

TEST(slew_dir_and_mag)
{
    slew_t s; slew_cfg_t c = { 2.0f, 20.0f, SLEW_BY_DIR };
    CHECK(slew_init(&s, &c, 0.0f) == DZ_OK);
    CHECK_NEAR(slew_update(&s, 1.0f, 0.1f), 0.2f, 1e-6);        /* 上升 2/s */
    CHECK_NEAR(slew_update(&s, -1.0f, 0.01f), 0.0f, 1e-6);      /* 下降 20/s */
    c.mode = SLEW_BY_MAG; c.rise_per_s = 1.0f; c.fall_per_s = 10.0f;
    CHECK(slew_init(&s, &c, -0.5f) == DZ_OK);
    CHECK_NEAR(slew_update(&s, -1.0f, 0.1f), -0.6f, 1e-6);      /* 负向加速也是 rise */
    CHECK_NEAR(slew_update(&s, 0.0f, 0.01f), -0.5f, 1e-6);      /* 负向减速是 fall */
    /* 跨零：-0.5 → +1，fall=10 走到 0 用 0.05 s，剩 0.05 s 按 rise=1 → +0.05 */
    CHECK_NEAR(slew_update(&s, 1.0f, 0.1f), 0.05f, 1e-6);
    /* 跨零但这一拍还到不了 0 */
    slew_reset(&s, 0.8f);
    CHECK_NEAR(slew_update(&s, -1.0f, 0.05f), 0.3f, 1e-6);
}

TEST(slew_edge_cases)
{
    slew_t s; slew_cfg_t c = { 0.0f, 0.0f, SLEW_BY_MAG };
    CHECK(slew_init(&s, &c, 0.0f) == DZ_OK);
    CHECK_NEAR(slew_update(&s, 3.0f, 0.001f), 3.0f, 1e-6);       /* 0 = 不限 */
    CHECK_NEAR(slew_update(&s, NAN, 0.001f), 3.0f, 1e-6);        /* NaN 保持 */
    CHECK_NEAR(slew_update(&s, 1.0f, 0.0f), 3.0f, 1e-6);         /* dt 非法保持 */
    c.rise_per_s = -1.0f; CHECK(slew_init(&s, &c, 0.0f) == DZ_EINVAL);
    c.rise_per_s = 1.0f; c.mode = (slew_mode_t)7; CHECK(slew_init(&s, &c, 0.0f) == DZ_EINVAL);
    CHECK(slew_update(0, 1.0f, 0.1f) == 0.0f);
    CHECK(slew_selftest() == DZ_OK);
}

/* 和一阶电机模型串起来：1 kHz，目标 0→1→0；起步 rise=2/s 用 0.5 s，刹车 fall=10/s 用 0.1 s */
TEST(slew_with_motor_model)
{
    slew_t s; slew_cfg_t c = { 2.0f, 10.0f, SLEW_BY_MAG };
    CHECK(slew_init(&s, &c, 0.0f) == DZ_OK);
    const float dt = 0.001f, tau = 0.05f;
    float w = 0.0f, t_up = -1.0f, t_dn = -1.0f, u;
    for (int k = 0; k < 2000; k++) {
        float tgt = k < 1000 ? 1.0f : 0.0f;
        u = slew_update(&s, tgt, dt);
        w += (u - w) * dt / tau;
        if (t_up < 0 && u >= 1.0f - 1e-5f) t_up = (float)(k + 1) * dt;
        if (k >= 1000 && t_dn < 0 && u <= 1e-5f) t_dn = (float)(k + 1 - 1000) * dt;
    }
    CHECK_NEAR(t_up, 0.5f, 0.002);
    CHECK_NEAR(t_dn, 0.1f, 0.002);
    CHECK(fabsf(w) < 0.02f);
}

/* 编码器模型：每转 cpr 个边沿，转速 rps；1 kHz 轮询 */
static float run_mt(mtspeed_t *m, float rps, uint32_t t0, uint32_t dur_us, float *m_method_std, float *mt_std, float *m20_std)
{
    int32_t ring[20] = {0}; int ri = 0, rsum = 0; double s3 = 0, q3 = 0;
    float cpr = m->cfg.counts_per_rev;
    double period = 1e6 / (fabs(rps) * cpr);
    double next = t0 + period * 0.37;
    int32_t win_cnt = 0; double s1 = 0, s2 = 0, q1 = 0, q2 = 0; int n = 0;
    for (uint32_t dt = 0; dt <= dur_us; dt += 1000u) {
        uint32_t t = t0 + dt;
        while (next <= (double)t0 + dt) { mtspeed_edge(m, (uint32_t)(int64_t)next, rps >= 0 ? 1 : -1); next += period; win_cnt++; }
        mtspeed_poll(m, t);
        rsum += win_cnt - ring[ri]; ring[ri] = win_cnt; ri = (ri + 1) % 20;
        if (dt > dur_us / 2) {                      /* 后半段统计 */
            float mm = (float)win_cnt / cpr / 1e-3f; /* M 法：每 1 ms 的边沿数 */
            float mt = mtspeed_rps(m);
            float m20 = (float)rsum / cpr / 20e-3f;   /* encoder window_n=20 的做法 */
            s3 += m20; q3 += m20 * m20;
            s1 += mm; q1 += mm * mm; s2 += mt; q2 += mt * mt; n++;
        }
        win_cnt = 0;
    }
    if (m_method_std) *m_method_std = (float)sqrt(fmax(0, q1 / n - (s1 / n) * (s1 / n)));
    if (mt_std) *mt_std = (float)sqrt(fmax(0, q2 / n - (s2 / n) * (s2 / n)));
    if (m20_std) *m20_std = (float)sqrt(fmax(0, q3 / n - (s3 / n) * (s3 / n)));
    return mtspeed_rps(m);
}

TEST(mtspeed_low_speed_vs_m_method)
{
    mtspeed_t m; mtspeed_cfg_t c = { 52.0f, 300000u };   /* 13 线 × 4 倍频的低线数电机（裸轴） */
    CHECK(mtspeed_init(&m, &c) == DZ_OK);
    float sd_m, sd_mt, sd_m20;
    float v = run_mt(&m, 1.9f, 0u, 2000000u, &sd_m, &sd_mt, &sd_m20);   /* 约 99 边沿/s：每 10 个周期 1 个边沿 */
    CHECK_NEAR(v, 1.9f, 0.002);
    printf("    1.9 rps：M 法 1ms 窗口 标准差 %.2f rps；20ms 窗口 %.3f rps（另有约 10 ms 延迟）；M/T %.4f rps\n", sd_m, sd_m20, sd_mt);
    CHECK(sd_mt < 0.2f * sd_m20);
    CHECK(sd_mt < 0.05f * sd_m);
}

TEST(mtspeed_decel_timeout_reverse_wrap)
{
    mtspeed_t m; mtspeed_cfg_t c = { 20.0f, 200000u };
    CHECK(mtspeed_init(&m, &c) == DZ_OK);
    CHECK(mtspeed_rps(&m) == 0.0f);
    float v = run_mt(&m, 5.0f, 0u, 500000u, 0, 0, 0);
    CHECK_NEAR(v, 5.0f, 0.01);
    /* 突然停转：没新边沿时读数要往下走，超时后归零 */
    uint32_t t_stop = 500000u;
    mtspeed_poll(&m, t_stop + 50000u);
    CHECK(mtspeed_rps(&m) < 1.01f);                    /* ≤ 1 边沿 / 50 ms = 1 rps */
    mtspeed_poll(&m, t_stop + 250000u);
    CHECK(mtspeed_rps(&m) == 0.0f);
    /* 停后重新起步：第一拍只当起点，不会用停车前的旧边沿算出一个很小的速度 */
    v = run_mt(&m, -3.0f, t_stop + 300000u, 400000u, 0, 0, 0);
    CHECK_NEAR(v, -3.0f, 0.01);
    /* 32 位 µs 回绕 */
    CHECK(mtspeed_init(&m, &c) == DZ_OK);
    v = run_mt(&m, 4.0f, 0xFFFFFFFFu - 200000u, 600000u, 0, 0, 0);
    CHECK_NEAR(v, 4.0f, 0.01);
    c.counts_per_rev = 0.0f; CHECK(mtspeed_init(&m, &c) == DZ_EINVAL);
    c.counts_per_rev = 1.0f; c.timeout_us = 0u; CHECK(mtspeed_init(&m, &c) == DZ_EINVAL);
    CHECK(mtspeed_selftest() == DZ_OK);
}

void suite_ctrlparts(void)
{
    RUN(slew_dir_and_mag); RUN(slew_edge_cases); RUN(slew_with_motor_model);
    RUN(mtspeed_low_speed_vs_m_method); RUN(mtspeed_decel_timeout_reverse_wrap);
}
