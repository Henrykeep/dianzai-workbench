#include <math.h>
/* 新模块：spsc、key、qd4310、ssd1306、ball_beam。 */
#include <string.h>
#include "tt.h"
#include "spsc.h"
#include "key.h"
#include "qd4310.h"
#include "ssd1306.h"
#include "ball_beam.h"
#include "dzctl.h"

TEST(spsc_basic_and_wrap)
{
    typedef struct { uint32_t t; int16_t x; } smp_t;
    smp_t st[8], s, o;
    spsc_t q;
    uint32_t i;
    CHECK(spsc_selftest() == DZ_OK);
    CHECK(spsc_init(&q, st, sizeof s, 0) == DZ_EINVAL);
    CHECK(spsc_init(&q, st, sizeof s, 8) == DZ_OK);
    q.head = q.tail = 0xFFFFFFFCu;                  /* 跨越 32 位回绕 */
    for (i = 0; i < 20; i++) {
        s.t = i; s.x = (int16_t)(-(int)i);
        CHECK(spsc_push(&q, &s) == DZ_OK);
        CHECK(spsc_pop(&q, &o) && o.t == i && o.x == -(int)i);
    }
    CHECK(spsc_count(&q) == 0 && !spsc_pop(&q, &o));
}

TEST(key_events)
{
    dz_key_t k;
    key_cfg_t c = { PAL_ID_NONE, 20, 500, 100 };
    uint32_t t, n_rep = 0, n_long = 0, n_short = 0;
    CHECK(key_selftest() == DZ_OK);
    CHECK(key_init(&k, &(key_cfg_t){ PAL_ID_NONE, 20, 10, 0 }) == DZ_EINVAL);
    CHECK(key_init(&k, &c) == DZ_OK);
    for (t = 0xFFFFFF00u; t != 0x00000400u; t++) {   /* 跨回绕按住约 1.28 s */
        key_event_t e = key_feed(&k, true, t);
        n_long += e == KEY_EV_LONG; n_rep += e == KEY_EV_REPEAT; n_short += e == KEY_EV_SHORT;
    }
    CHECK(n_long == 1 && n_rep == 7 && n_short == 0);
    for (; t != 0x00000500u; t++) n_short += key_feed(&k, false, t) == KEY_EV_SHORT;
    CHECK(n_short == 0 && !key_is_down(&k));         /* 长按后松开不再报短按 */
    for (; t != 0x00000540u; t++) key_feed(&k, true, t);
    for (; t != 0x00000600u; t++) n_short += key_feed(&k, false, t) == KEY_EV_SHORT;
    CHECK(n_short == 1);
}

TEST(qd4310_codec_and_resync)
{
    uint8_t f[5], rx[40];
    qd4310_t m;
    int i;
    CHECK(qd4310_selftest() == DZ_OK);
    qd4310_encode(1, QD_CMD_SPEED, (uint16_t)(int16_t)-32767, f);
    CHECK(f[0] == 1 && f[1] == 4 && f[2] == 0x01 && f[3] == 0x80 && f[4] == qd4310_crc8(f, 4));
    CHECK(qd4310_init(&m, PAL_ID_NONE, 1) == DZ_OK);
    /* 两个好帧之间夹一个 CRC 错帧和杂字节 */
    for (i = 0; i < 40; i++) rx[i] = 0xAA;
    {
        uint8_t g[10] = { 1, 0, 0, 0x00, 0xC0, 0x00, 0x40, 0x00, 0x40, 0 };   /* cur −5 A, spd 500, ang 90° */
        g[9] = qd4310_crc8(g, 9);
        memcpy(&rx[0], g, 10);
        memcpy(&rx[12], g, 10); rx[21] ^= 0x01;      /* CRC 错 */
        memcpy(&rx[25], g, 10);
    }
    CHECK(qd4310_feed(&m, rx, 13, 100));
    CHECK_NEAR(m.fb.current_a, -5.0, 0.01); CHECK_NEAR(m.fb.speed_rpm, 500.0, 0.1); CHECK_NEAR(m.fb.angle_deg, 90.0, 0.01);
    CHECK(qd4310_feed(&m, &rx[13], 27, 200));
    CHECK(m.rx_ok == 2 && m.rx_err >= 1 && m.fb.t_ms == 200);
    CHECK(qd4310_online(&m, 250, 100) && !qd4310_online(&m, 301, 100));
    CHECK(qd4310_set_angle_deg(&m, 0.0f / 0.0f) == DZ_EINVAL);
}

static uint8_t cap_cmd[64], cap_n;
static uint32_t cap_data;
static dz_err_t cap_write(void *ctx, bool is_data, const uint8_t *b, uint16_t n)
{
    (void)ctx;
    if (is_data) cap_data += n;
    else { for (uint16_t i = 0; i < n && cap_n < sizeof cap_cmd; i++) cap_cmd[cap_n++] = b[i]; }
    return DZ_OK;
}

TEST(ssd1306_fb_text_flush)
{
    static ssd1306_t d;
    CHECK(ssd1306_selftest() == DZ_OK);
    CHECK(ssd1306_init(&d, cap_write, NULL, 48, false) == DZ_EINVAL);
    cap_n = 0; cap_data = 0;
    CHECK(ssd1306_init(&d, cap_write, NULL, 32, true) == DZ_OK);
    CHECK(cap_cmd[0] == 0xAE && cap_cmd[4] == 31 && cap_cmd[12] == 0xA0 && cap_cmd[15] == 0x02 && cap_cmd[cap_n - 1] == 0xAF);
    ssd1306_pixel(&d, 3, 9, true);
    CHECK(d.buf[128 + 3] == 0x02 && ssd1306_get_pixel(&d, 3, 9));
    ssd1306_pixel(&d, 0, 40, true);                  /* 128×32 越界 */
    CHECK(!ssd1306_get_pixel(&d, 0, 40));
    CHECK(ssd1306_text(&d, 0, 4, "x") == 0);         /* 32 高只有 4 行 */
    CHECK(ssd1306_label_float(&d, 0, 0, "KP", 0.72f, 3) == 8);   /* "KP 0.720" */
    CHECK(memcmp(&d.buf[8 * 3], ssd1306_font8x8['0' - 0x20], 8) == 0);
    CHECK(ssd1306_label_float(&d, 0, 1, "", -1.5f, 1) == 4);     /* "-1.5" */
    CHECK(memcmp(&d.buf[128 + 8], ssd1306_font8x8['1' - 0x20], 8) == 0);
    cap_data = 0; CHECK(ssd1306_flush(&d) == DZ_OK && cap_data == 512);
    ssd1306_fill_rect(&d, 0, 0, 128, 32, true);
    CHECK(d.buf[0] == 0xFF && d.buf[511] == 0xFF);
}

static ball_beam_cfg_t bb_cfg(void)
{
    ball_beam_cfg_t c = { 0.55f, 0.20f, 0.07f, 0.72f, 320.0f, 0.016f, 0.055f, 55.0f, 2.5f, 0.5f,
                          5.5f, 220.0f, 120u, 600u, 1.0f, 0u, 0.0f, 0u, 0.0f, 0.0f, 0.0f, 0u, {0}, {0}, 0.0f, 0.0f };
    return c;
}

TEST(ball_beam_estimator_and_limits)
{
    ball_beam_t b;
    ball_beam_cfg_t c = bb_cfg();
    uint32_t t;
    float a = 0;
    CHECK(ball_beam_selftest() == DZ_OK);
    c.beta = 3.0f; CHECK(ball_beam_init(&b, &c) == DZ_EINVAL);    /* 超出 α-β 稳定域 */
    c = bb_cfg(); c.dir = 0.5f; CHECK(ball_beam_init(&b, &c) == DZ_EINVAL);
    c = bb_cfg(); c.rate_max = 0; c.ki = 0;
    CHECK(ball_beam_init(&b, &c) == DZ_OK);
    for (t = 0; t <= 2000; t += 40) ball_beam_sample(&b, 50.0f + 0.1f * (float)t, t);   /* 100 px/s 匀速 */
    CHECK_NEAR(b.v, 100.0, 1.0);
    CHECK_NEAR(b.x, 250.0, 1.0);
    a = ball_beam_update(&b, 250.0f, 0, 2000, 0.01f);
    /* e = 250 − (250 + 100·0.07) = −7 → v_des = −5.04；θ = 0.016·(−5.04−100) */
    CHECK_NEAR(a, -1.68, 0.03);
    ball_beam_sample(&b, 0, 2000);                   /* 重复时间戳：丢弃 */
    CHECK_NEAR(b.x, 250.0, 1.0);
    /* 斜率限制 */
    c = bb_cfg(); c.ki = 0; ball_beam_init(&b, &c);
    ball_beam_sample(&b, -1000, 0);
    a = ball_beam_update(&b, 0, 0, 0, 0.01f);
    CHECK_NEAR(a, 2.2, 1e-4);                         /* 220°/s × 10 ms */
    for (t = 10; t <= 100; t += 10) a = ball_beam_update(&b, 0, 0, t, 0.01f);
    CHECK_NEAR(a, 5.12, 0.01);                        /* vel_max 320 × 0.016 */
    for (; t <= 200; t += 10) a = ball_beam_update(&b, 0, 0, t, 0.01f);
    CHECK(ball_beam_state(&b) == BB_HOLD);            /* 超过 hold 120 ms：保持 */
    CHECK_NEAR(a, 5.12, 0.01);
    for (; t <= 800; t += 10) a = ball_beam_update(&b, 0, 0, t, 0.01f);
    CHECK(ball_beam_state(&b) == BB_LOST && a == 0.0f);
    ball_beam_sample(&b, 10, t);
    CHECK(ball_beam_state(&b) == BB_TRACK && b.v == 0.0f);
}

TEST(ball_beam_integral)
{
    ball_beam_t b;
    ball_beam_cfg_t c = bb_cfg();
    uint32_t t;
    c.pos_k = 0; c.lead_s = 0; c.rate_max = 0;
    ball_beam_init(&b, &c);
    for (t = 0; t <= 20000; t += 10) { if (t % 40 == 0) ball_beam_sample(&b, -30, t); ball_beam_update(&b, 0, 0, t, 0.01f); }
    CHECK_NEAR(b.integ, 2.5, 1e-4);                   /* 钳到 i_max */
    ball_beam_sample(&b, 30, t);
    ball_beam_update(&b, 0, 0, t, 0.01f);
    CHECK(b.integ < 1.26f && b.integ > 1.2f);         /* 变号衰减 ×0.5 后再积一步 */
    ball_beam_init(&b, &c);
    for (t = 0; t <= 1000; t += 10) { if (t % 40 == 0) ball_beam_sample(&b, -80, t); ball_beam_update(&b, 0, 0, t, 0.01f); }
    CHECK(b.integ == 0.0f);                           /* 积分区外不积 */
}

TEST(dzctl_param_and_estop)
{
    typedef struct { float kp; uint32_t ms; int16_t off; } p_t;
    static const dzctl_param_t d[] = { { "kp", 0, DZCTL_F32, 0.0f, 2.0f }, { "ms", 4, DZCTL_U32, 50.0f, 2000.0f },
                                       { "off", 8, DZCTL_I16, -100.0f, 100.0f } };
    p_t p = { 0.1f, 200u, 0 };
    dzctl_table_t t = { &p, d, 3u, 0xCAFEu };
    dzframe_t in, ack;
    float nan = 0.0f;
    CHECK(dzctl_selftest() == 0);
    memset(&in, 0, sizeof in); in.kind = DZF_PARAM_SET; in.id = 1; in.seq = 7;
    CHECK(dzframe_put_f32(&in, 9999.0f));
    CHECK(dzctl_handle(&t, &in, &ack));
    CHECK(ack.id == 1 && ack.seq == 7 && dzframe_get_u8(&ack, 0) == DZCTL_CLAMPED && p.ms == 2000u);
    memset(&in, 0, sizeof in); in.kind = DZF_PARAM_SET; in.id = 2;
    CHECK(dzframe_put_f32(&in, -42.4f) && dzctl_handle(&t, &in, &ack) && p.off == -42);
    nan = nan / nan;
    CHECK(dzctl_set(&t, 0, nan, 0) == DZCTL_BAD_VALUE && p.kp == 0.1f);         /* NaN 不写入 */
    memset(&in, 0, sizeof in); in.kind = DZF_PARAM_SET; in.id = 9;
    CHECK(dzctl_handle(&t, &in, &ack) && dzframe_get_u8(&ack, 0) == DZCTL_BAD_ID);
    memset(&in, 0, sizeof in); in.kind = DZF_DATA; in.id = DZCTL_ID_ESTOP;
    CHECK(dzctl_is_estop(&in) && !dzctl_handle(&t, &in, &ack));
    dzctl_heartbeat(&t, 3, &ack);
    CHECK(ack.kind == DZF_HEARTBEAT && dzframe_get_u32(&ack, 0) == 0xCAFEu);
}


/* 1.1.0 A/B 选项：每个 B 选项单独开，对比 A 的输出 */
static float bb_run(ball_beam_cfg_t c, float x_px, int steps)
{
    ball_beam_t b; float a = 0;
    if (ball_beam_init(&b, &c) != DZ_OK) return NAN;
    for (int k = 0; k < steps; k++) { ball_beam_sample(&b, x_px, (uint32_t)(k * 10)); a = ball_beam_update(&b, 0, 0, (uint32_t)(k * 10), 0.01f); }
    return a;
}

TEST(ball_beam_ab_options)
{
    ball_beam_cfg_t c = bb_cfg(); c.ki = 0; c.rate_max = 0;
    float a = bb_run(c, -30.0f, 20);
    CHECK_NEAR(a, 0.016 * 0.72 * 30, 1e-3);                  /* A：静止球，θ = vel_k·pos_k·e */
    ball_beam_cfg_t d = c; d.est_mode = BB_EST_DIFF_LPF;    /* B 估计器：静止球结果相同 */
    CHECK_NEAR(bb_run(d, -30.0f, 20), a, 1e-3);
    d = c; d.vel_max = 10.0f;                                /* 串级 v_des 被限住 */
    float cas = bb_run(d, -30.0f, 20);
    d.loop_mode = BB_LOOP_SINGLE;                            /* 单环不限 v_des */
    CHECK(bb_run(d, -30.0f, 20) > cas + 0.1f);
    d = c; d.stic_deg = 0.4f; d.stic_vel = 5.0f; d.stic_e = 10.0f;
    CHECK_NEAR(bb_run(d, -30.0f, 20), a + 0.4, 1e-3);        /* 静摩擦补偿沿误差方向 */
    CHECK_NEAR(bb_run(d, -5.0f, 20), 0.016 * 0.72 * 5, 1e-3);/* |e|<stic_e 不加 */
    d = c; d.bal_n = 3; d.bal_x[0] = -100; d.bal_x[1] = 0; d.bal_x[2] = 100;
    d.bal_deg[0] = 1.0f; d.bal_deg[1] = 0.0f; d.bal_deg[2] = -0.5f;
    CHECK_NEAR(ball_beam_bal_ff(&d, -50), 0.5, 1e-5);
    CHECK_NEAR(ball_beam_bal_ff(&d, 200), -0.5, 1e-5);
    CHECK_NEAR(bb_run(d, -30.0f, 20), a + 0.3, 1e-2);        /* x_now 含超前外推，静止球即 −30 */
    ball_beam_t b;
    d.bal_x[2] = -200; CHECK(ball_beam_init(&b, &d) == DZ_EINVAL);
    d = c; d.est_mode = 2; CHECK(ball_beam_init(&b, &d) == DZ_EINVAL);
}

void suite_modules(void)
{
    RUN(spsc_basic_and_wrap); RUN(key_events); RUN(qd4310_codec_and_resync);
    RUN(ssd1306_fb_text_flush); RUN(ball_beam_estimator_and_limits); RUN(ball_beam_integral); RUN(ball_beam_ab_options);
    RUN(dzctl_param_and_estop);
}
