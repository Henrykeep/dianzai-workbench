#include "tt.h"
#include <string.h>
#include <math.h>
#include <stdlib.h>
#include "vis.h"
#include "abobs.h"

TEST(vis_states_age_seq)
{
    vis_link_t l; vis_link_cfg_t c = { 50u, 200u, 0u };
    CHECK(vis_link_init(&l, &c) == DZ_OK);
    CHECK(vis_link_age_ms(&l, 10) == UINT32_MAX);
    CHECK(vis_link_poll(&l, 10) == VIS_LOST);
    vis_link_feed(&l, 254, 0, 20, true, 1.0f);
    vis_link_feed(&l, 255, 10, 30, true, 2.0f);
    vis_link_feed(&l, 2, 40, 60, true, 3.0f);                /* 255→2：丢了 0、1 */
    CHECK(l.drops == 2u);
    CHECK(vis_link_age_ms(&l, 70) == 10u);
    CHECK(vis_link_poll(&l, 70) == VIS_VALID);
    vis_link_feed(&l, 3, 50, 80, false, 0.0f);               /* 无效帧不刷新时效 */
    CHECK(l.invalid == 1u && vis_link_age_ms(&l, 120) == 60u);
    CHECK(vis_link_poll(&l, 120) == VIS_HELD);
    CHECK(vis_link_poll(&l, 261) == VIS_LOST);
    CHECK(strcmp(vis_state_name(VIS_HELD), "held") == 0);
    vis_link_feed(&l, 3, 60, 90, true, 9.0f);                /* 重复 seq 丢弃 */
    CHECK(l.x == 3.0f);
    c.lost_ms = 50; CHECK(vis_link_init(&l, &c) == DZ_EINVAL);
}

TEST(vis_latency_jitter)
{
    vis_link_t l; vis_link_cfg_t c = { 50u, 200u, 4u };
    vis_link_init(&l, &c);
    /* 相机时钟比 MCU 晚 1000 ms 起步；单程延迟 20、35、20、28 ms */
    uint32_t lat[] = { 20, 35, 20, 28, 25, 22 };
    for (unsigned i = 0; i < 6; i++) vis_link_feed(&l, (uint8_t)i, i * 33u, 1000u + i * 33u + lat[i], true, 0.0f);
    CHECK(l.lat_jitter_ms >= 0 && l.lat_jitter_ms <= 8);    /* 窗口滚动后最小值仍为 20 附近 */
    vis_link_init(&l, &c);
    vis_link_feed(&l, 0, 0, 1020, true, 0); vis_link_feed(&l, 1, 33, 1068, true, 0);
    CHECK(l.lat_jitter_ms == 15);
}

TEST(vis_calib_piecewise)
{
    vis_calib_t c; bool oor;
    float px[5] = { -150, -60, 0, 50, 140 }, mm[5] = { -100, -40, 0, 30, 90 };   /* 左右斜率不同 */
    CHECK(vis_calib_init(&c, px, mm, 5) == DZ_OK);
    CHECK_NEAR(vis_calib_apply(&c, -30, &oor), -20.0, 1e-4); CHECK(!oor);
    CHECK_NEAR(vis_calib_apply(&c, 25, &oor), 15.0, 1e-4);
    CHECK_NEAR(vis_calib_apply(&c, 140, &oor), 90.0, 1e-4); CHECK(!oor);
    CHECK_NEAR(vis_calib_apply(&c, 230, &oor), 150.0, 1e-3); CHECK(oor);   /* 最外段斜率 60/90 外推 */
    CHECK_NEAR(vis_calib_apply(&c, -195, &oor), -130.0, 1e-3); CHECK(oor);
    float bad[3] = { 0, 0, 1 };
    CHECK(vis_calib_init(&c, bad, mm, 3) == DZ_EINVAL);
    CHECK(vis_calib_init(&c, px, mm, 1) == DZ_EINVAL);
    CHECK(vis_selftest() == DZ_OK);
}

TEST(abobs_noise_gate_coast)
{
    abobs_t o; abobs_cfg_t c = { 0.4f, 0.08f, 20.0f, 0.1f };
    CHECK(abobs_init(&o, &c) == DZ_OK);
    srand(3);
    double err_ab = 0, err_diff = 0; float zl = 0;
    for (int k = 0; k < 400; k++) {
        float t = k * 0.02f, z = 50.0f * t + ((float)rand() / RAND_MAX - 0.5f) * 4.0f;
        abobs_update(&o, z, 0.02f);
        if (k > 100) { err_ab += fabs(o.v - 50.0); err_diff += fabs((z - zl) / 0.02 - 50.0); }
        zl = z;
    }
    CHECK(err_ab < err_diff * 0.3);                          /* 速度估计远好于直接差分 */
    CHECK(!abobs_update(&o, o.x + 500.0f, 0.02f));           /* 野值被门限挡掉 */
    CHECK(o.rejected == 1u);
    float x0 = o.x;
    abobs_predict(&o, 0.05f); CHECK(o.x > x0);               /* 外推 */
    abobs_predict(&o, 0.1f);  CHECK(o.v == 0.0f);            /* 超过 max_predict_s 速度清零 */
    c.beta = 3.5f; CHECK(abobs_init(&o, &c) == DZ_EINVAL);
    CHECK(abobs_selftest() == DZ_OK);
}

void suite_vision(void) { RUN(vis_states_age_seq); RUN(vis_latency_jitter); RUN(vis_calib_piecewise); RUN(abobs_noise_gate_coast); }
