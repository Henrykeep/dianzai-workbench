/* 2026H_ball 参考实例的测试：全部用模拟数据，不需要硬件、不需要 Jetson。 */
#include <string.h>
#include "tt.h"
#include "project_gen.h"
#include "vision_link.h"

int tt_fail, tt_pass;

static int feed(vision_link_t *v, const char *s, vision_frame_t *f)
{
    int n = 0;
    for (; *s; s++) n += vision_link_feed(v, (uint8_t)*s, f);
    return n;
}

TEST(vision_link_parser)
{
    vision_link_t v; vision_frame_t f = {0}; char b[40];
    vision_link_init(&v);
    vision_frame_t in = { -12, 480, true };
    vision_link_format(b, sizeof b, &in);
    CHECK(feed(&v, b, &f) == 1 && f.x == -12 && f.y == 480 && f.found);
    CHECK(feed(&v, "$B,1,2,1*00\n", &f) == 0 && v.bad == 1);               /* 校验错 */
    CHECK(feed(&v, "garbage$B,1,2", &f) == 0);
    CHECK(feed(&v, b, &f) == 1 && v.bad == 2);                              /* 半帧被新的 $ 打断 */
    CHECK(feed(&v, "$B,99999999,1,1*00\n", &f) == 0);                        /* 超长数字 */
    CHECK(feed(&v, "$B,1,2,7*00\n", &f) == 0);                               /* found 只能 0/1 */
    char longl[64]; memset(longl, '1', sizeof longl); longl[0] = '$'; longl[63] = 0;
    CHECK(feed(&v, longl, &f) == 0 && feed(&v, b, &f) == 1);                 /* 超长后能恢复 */
    CHECK(v.good == 3);
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
    RUN(vision_link_parser); RUN(vision_subsys_mock); RUN(ball_subsys_mock); RUN(generated_tables_consistent);
    printf("\n通过 %d，失败 %d\n", tt_pass, tt_fail);
    return tt_fail ? 1 : 0;
}
