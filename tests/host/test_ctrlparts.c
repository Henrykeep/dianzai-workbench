/* G7 控制环常用件：不对称变化率限制。 */
#include "tt.h"
#include <math.h>
#include <stdint.h>
#include "slew.h"

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

void suite_ctrlparts(void)
{
    RUN(slew_dir_and_mag); RUN(slew_edge_cases); RUN(slew_with_motor_model);
}
