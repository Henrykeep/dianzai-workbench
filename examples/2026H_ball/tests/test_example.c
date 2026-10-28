/* 2026H_ball 参考实例的测试：全部用模拟数据，不需要硬件、不需要相机。 */
#include <string.h>
#include "tt.h"
#include "project_gen.h"
#include "dzframe.h"
#include "ball_beam.h"
#include "cp_vision_cpu.h"

int tt_fail, tt_pass;

TEST(vision_channel_codec_and_python_interop)
{
    static const uint8_t py[] = PY_BALL_FRAME;            /* host/maixcam/ball_sender.py 编出来的帧 */
    cp_vision_cpu_ball_t in = { 0x09, -12, 123456 }, out = { 0, 0, 0 };
    dzframe_t f, g;
    dzframe_parser_t p;
    uint8_t raw[DZFRAME_MAX_FRAME];
    size_t n, i;
    int k = 0;
    CHECK(cp_vision_cpu_ball_encode(&in, 7, &f) && f.len == CP_VISION_CPU_BALL_SIZE && f.len == 7);
    n = dzframe_encode(raw, sizeof raw, &f);
    dzframe_parser_init(&p);
    for (i = 0; i < n; i++) k += dzframe_feed(&p, raw[i], &g);
    CHECK(k == 1 && cp_vision_cpu_ball_decode(&g, &out));
    CHECK(out.flags == 0x09 && out.x_px == -12 && out.cam_ms == 123456u);
    k = 0;
    for (i = 0; i < sizeof py; i++) k += dzframe_feed(&p, py[i], &g);
    CHECK(k == 1 && cp_vision_cpu_ball_decode(&g, &out));
    CHECK(out.flags == 0x09 && out.x_px == -123 && out.cam_ms == 4000000000u);
    raw[n - 1] ^= 0xFF; k = 0;                             /* CRC 错：丢弃 */
    for (i = 0; i < n; i++) k += dzframe_feed(&p, raw[i], &g);
    CHECK(k == 0);
    g.id = 9; CHECK(!cp_vision_cpu_ball_decode(&g, &out));
}

TEST(vision_subsys)
{
    shared_state_t st = {0}; const params_t *p = &g_project_params[PROFILE_BASE];
    SUBSYS_VISION.init(&st, p);
    SUBSYS_VISION.step(&st, p, 10);
    CHECK(!st.vision_out.new_sample);
    st.io_in.cam_seq = 1; st.io_in.cam_flags = 0x08; st.io_in.cam_x_px = 5;   /* 无 valid 位 */
    SUBSYS_VISION.step(&st, p, 20);
    CHECK(!st.vision_out.new_sample);
    st.io_in.cam_seq = 2; st.io_in.cam_flags = 0x09; st.io_in.cam_rx_ms = 25;
    SUBSYS_VISION.step(&st, p, 30);
    CHECK(st.vision_out.new_sample && st.vision_out.x_px == 5.0f && st.vision_out.t_ms == 25u);
    SUBSYS_VISION.step(&st, p, 35);
    CHECK(!st.vision_out.new_sample);
    CHECK(SUBSYS_VISION.selftest() == DZ_OK);
}

/* 简化钢珠物理：x'' = k·sin(θ)，用来检查闭环方向与稳定性（不是真实机械参数）。 */
TEST(ball_subsys_closed_loop_toy)
{
    shared_state_t st = {0}; const params_t *p = &g_project_params[PROFILE_BASE];
    float x = -80.0f, v = 0.0f, max_abs = 0.0f;
    uint32_t t;
    CHECK(SUBSYS_BALL.init(&st, p) == DZ_OK);
    CHECK_NEAR(st.beam_out.target_abs_deg, p->beam_zero_deg, 1e-4);
    for (t = 0; t < 8000; t += 10) {
        if (t % 40 == 0) { st.vision_out.new_sample = true; st.vision_out.x_px = x; st.vision_out.t_ms = t; }
        SUBSYS_BALL.step(&st, p, t);
        st.vision_out.new_sample = false;
        if (st.beam_out.angle_deg > max_abs) max_abs = st.beam_out.angle_deg;
        if (-st.beam_out.angle_deg > max_abs) max_abs = -st.beam_out.angle_deg;
        v += 60.0f * st.beam_out.angle_deg * 0.01f;        /* px/s² per ° */
        x += v * 0.01f;
    }
    CHECK(fabsf(x) < 15.0f);
    CHECK(max_abs <= p->angle_max_deg + 1e-4f);
    CHECK(st.beam_out.target_abs_deg >= p->beam_min_deg && st.beam_out.target_abs_deg <= p->beam_max_deg);
    for (; t < 9000; t += 10) SUBSYS_BALL.step(&st, p, t);   /* 视觉断了 */
    CHECK(st.beam_out.state == BB_LOST);
    CHECK_NEAR(st.beam_out.target_abs_deg, p->beam_zero_deg, 1e-3);
}

TEST(ball_feedforward_and_profile_switch)
{
    shared_state_t a = {0}, b = {0};
    const params_t *pf = &g_project_params[PROFILE_FAST];
    SUBSYS_BALL.init(&a, pf);
    a.vision_out = (st_vision_out_t){ true, 0.0f, 0 };
    a.chassis_out.accel_mps2 = 1.0f;
    SUBSYS_BALL.step(&a, pf, 0);
    SUBSYS_BALL.init(&b, pf);
    b.vision_out = (st_vision_out_t){ true, 0.0f, 0 };
    SUBSYS_BALL.step(&b, pf, 0);
    CHECK(a.beam_out.angle_deg > b.beam_out.angle_deg);     /* 加速前倾 */
    CHECK(a.beam_out.angle_deg <= pf->angle_max_deg);
}

TEST(generated_tables_consistent)
{
    CHECK(PROJECT_N_SUBSYS == 3u);
    CHECK(g_project_tests[1].profile == PROFILE_FAST);
    CHECK(g_project_params[PROFILE_BASE].counts_per_rev == 1456.0f);
    CHECK_NEAR(g_project_params[PROFILE_BASE].wheel_circ_m, 0.2041, 1e-6);
    CHECK_NEAR(g_project_params[PROFILE_FAST].vel_k, 0.018, 1e-6);
    CHECK(g_project_params[PROFILE_BASE].ff_gain == 0.0f && g_project_params[PROFILE_FAST].ff_gain > 1.29f);
    CHECK(g_project_params[PROFILE_BASE].vision_timeout_ms == 600u);
}

int main(void)
{
    RUN(vision_channel_codec_and_python_interop); RUN(vision_subsys); RUN(ball_subsys_closed_loop_toy);
    RUN(ball_feedforward_and_profile_switch); RUN(generated_tables_consistent);
    printf("\n通过 %d，失败 %d\n", tt_pass, tt_fail);
    return tt_fail ? 1 : 0;
}
