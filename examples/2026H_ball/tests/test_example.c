/* 2026H_ball 参考实例的测试：全部用模拟数据，不需要硬件、不需要 Jetson。 */
#include <string.h>
#include "tt.h"
#include "project_gen.h"
#include "dzframe.h"
#include "cp_vision_cpu.h"

int tt_fail, tt_pass;

TEST(vision_channel_codec)
{
    /* 生成的通道编解码：主控与 Jetson 两端字段顺序由同一份 board.yaml 决定 */
    cp_vision_cpu_ball_t in = { -12, 480, 1 }, out = { 0, 0, 0 };
    dzframe_t f;
    CHECK(cp_vision_cpu_ball_encode(&in, 7, &f) && f.len == CP_VISION_CPU_BALL_SIZE);
    uint8_t raw[DZFRAME_MAX_FRAME]; size_t n = dzframe_encode(raw, sizeof raw, &f);
    dzframe_parser_t p; dzframe_parser_init(&p); dzframe_t g; int k = 0;
    for (size_t i = 0; i < n; i++) k += dzframe_feed(&p, raw[i], &g);
    CHECK(k == 1 && cp_vision_cpu_ball_decode(&g, &out));
    CHECK(out.x_px == -12 && out.y_px == 480 && out.found == 1);
    g.id = 9;  CHECK(!cp_vision_cpu_ball_decode(&g, &out));            /* 别的通道 */
    g.id = CP_VISION_CPU_CH_BALL; g.len = 4; CHECK(!cp_vision_cpu_ball_decode(&g, &out));   /* 长度不符 */
    CHECK(cp_vision_cpu_params[0].id == CP_VISION_CPU_PARAM_THRESH);
}

TEST(vision_subsys_mock)
{
    shared_state_t st = {0}; const params_t *p = &g_project_params[PROFILE_BASE];
    SUBSYS_VISION.init(&st, p);
    SUBSYS_VISION.step(&st, p, 10);
    CHECK(!st.vision_out.valid);                                             /* 还没收到帧 */
    st.io_in = (st_io_in_t){ .cam_x_px = 340, .cam_y_px = 220, .cam_found = true, .cam_seq = 1, .cam_rx_ms = 100 };
    SUBSYS_VISION.step(&st, p, 120);
    CHECK(st.vision_out.valid);
    CHECK_NEAR(st.vision_out.x_mm, 20 * p->mm_per_px, 1e-4);
    CHECK_NEAR(st.vision_out.y_mm, -20 * p->mm_per_px, 1e-4);
    SUBSYS_VISION.step(&st, p, 100 + p->vision_timeout_ms + 1);
    CHECK(!st.vision_out.valid);                                             /* 超时 */
    st.io_in.cam_found = false; st.io_in.cam_rx_ms = 300;
    SUBSYS_VISION.step(&st, p, 300);
    CHECK(!st.vision_out.valid);                                             /* 未识别到 */
    CHECK(SUBSYS_VISION.selftest() == DZ_OK);
}

TEST(ball_subsys_mock)
{
    shared_state_t st = {0}; const params_t *p = &g_project_params[PROFILE_BASE];
    CHECK(SUBSYS_BALL.init(&st, p) == DZ_OK);
    CHECK(st.ball_out.servo_x_us == p->servo_mid_us);
    st.vision_out = (st_vision_out_t){ .x_mm = 10.0f, .y_mm = 0.0f, .valid = true };
    SUBSYS_BALL.step(&st, p, 0);
    CHECK(st.ball_out.servo_x_us < p->servo_mid_us);                         /* 球在 +x，舵机往 -x 打 */
    CHECK(st.ball_out.servo_y_us == p->servo_mid_us);
    st.vision_out.x_mm = 1e6f;
    SUBSYS_BALL.step(&st, p, 10);
    CHECK(st.ball_out.servo_x_us == p->servo_mid_us - p->servo_span_us);    /* 限幅 */
    uint16_t held = st.ball_out.servo_x_us;
    st.vision_out.valid = false;
    SUBSYS_BALL.step(&st, p, 20);
    CHECK(st.ball_out.servo_x_us == held);                                   /* 丢视觉保持 */
    SUBSYS_BALL.on_mode(&st, SUBSYS_MODE_ESTOP);
    CHECK(st.ball_out.servo_x_us == 1500);
    /* 前馈：moving 档下底盘加速度会改变 x 输出 */
    const params_t *pm = &g_project_params[PROFILE_MOVING];
    shared_state_t a = {0}, b = {0};
    SUBSYS_BALL.init(&a, pm); a.vision_out.valid = true; a.chassis_out.accel_rps2 = 2.0f;
    SUBSYS_BALL.step(&a, pm, 0);
    SUBSYS_BALL.init(&b, pm); b.vision_out.valid = true;
    SUBSYS_BALL.step(&b, pm, 0);
    CHECK(a.ball_out.servo_x_us > b.ball_out.servo_x_us);
}

TEST(generated_tables_consistent)
{
    CHECK(PROJECT_N_SUBSYS == 3u);
    CHECK(g_project_tests[1].profile == PROFILE_MOVING);
    CHECK(g_project_tests[1].time_limit_ms == 60000u);
    CHECK(g_project_params[PROFILE_MOVING].ball_ff > 0.0f && g_project_params[PROFILE_BASE].ball_ff == 0.0f);
    for (unsigned i = 0; i < PROJECT_N_SUBSYS; i++) CHECK(g_project_subsys[i]->period_ms > 0);
}

int main(void)
{
    RUN(vision_channel_codec); RUN(vision_subsys_mock); RUN(ball_subsys_mock); RUN(generated_tables_consistent);
    printf("\n通过 %d，失败 %d\n", tt_pass, tt_fail);
    return tt_fail ? 1 : 0;
}
