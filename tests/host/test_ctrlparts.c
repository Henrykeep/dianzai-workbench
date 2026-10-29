/* G7 控制环常用件：不对称变化率限制、变周期 M/T 测速、平面五点标定。 */
#include "tt.h"
#include <math.h>
#include <stdint.h>
#include "slew.h"
#include "mtspeed.h"
#include "vis.h"

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

/* 平面标定：用一个已知透视变换生成"相机看到的像素"，再反求 */
static void persp(float x, float y, float *u, float *v)
{
    /* 600×600 mm 屏幕，相机偏左下斜看：一个任意的非仿射单应 */
    const float H[9] = { 0.42f, 0.06f, 40.0f, -0.03f, 0.38f, 25.0f, 0.00021f, 0.00012f, 1.0f };
    float w = H[6] * x + H[7] * y + H[8];
    *u = (H[0] * x + H[1] * y + H[2]) / w;
    *v = (H[3] * x + H[4] * y + H[5]) / w;
}

TEST(vis_plane_five_point)
{
    float wx[4] = { 0, 600, 600, 0 }, wy[4] = { 0, 0, 600, 600 }, px[4], py[4];
    for (int i = 0; i < 4; i++) persp(wx[i], wy[i], &px[i], &py[i]);
    float cu, cv; persp(300, 300, &cu, &cv);
    float chk[4] = { cu, cv, 300, 300 };
    vis_plane_t p;
    CHECK(vis_plane_init(&p, px, py, wx, wy, chk) == DZ_OK);
    CHECK(p.check_err >= 0.0f && p.check_err < 0.05f);
    float worst = 0, worst_rt = 0;
    for (int i = 0; i <= 12; i++) for (int j = 0; j <= 12; j++) {
        float X = 50.0f * i, Y = 50.0f * j, u, v, x, y, u2, v2;
        persp(X, Y, &u, &v);
        CHECK(vis_plane_to_world(&p, u, v, &x, &y) == DZ_OK);
        worst = fmaxf(worst, hypotf(x - X, y - Y));
        CHECK(vis_plane_to_pixel(&p, x, y, &u2, &v2) == DZ_OK);
        worst_rt = fmaxf(worst_rt, hypotf(u2 - u, v2 - v));
    }
    printf("    网格 169 点：像素→平面最大误差 %.4f mm，往返最大误差 %.5f px\n", worst, worst_rt);
    CHECK(worst < 0.1f);
    CHECK(worst_rt < 0.01f);
    /* 只用四角做"双线性/仿射"会错多少：对照，说明为什么要单应 */
    float u, v; persp(300, 300, &u, &v);
    float aff_x = (u - px[0]) / (px[1] - px[0]) * 600.0f;   /* 按上边两角线性插值 */
    printf("    对照：中心点按上边两角线性插值得 x=%.1f mm（真值 300）\n", aff_x);
    /* 中心点点错 8 像素：验收误差要明显变大 */
    chk[0] += 8.0f;
    CHECK(vis_plane_init(&p, px, py, wx, wy, chk) == DZ_OK);
    printf("    中心点偏 8 px → check_err = %.1f mm\n", p.check_err);
    CHECK(p.check_err > 10.0f);
    CHECK(vis_plane_init(&p, px, py, wx, wy, 0) == DZ_OK && p.check_err == -1.0f);
    /* 三点共线 / 重复点拒绝 */
    float bx[4] = { 0, 100, 200, 0 }, by[4] = { 0, 0, 0, 100 };
    CHECK(vis_plane_init(&p, bx, by, wx, wy, 0) == DZ_EINVAL);
    float nx[4] = { NAN, 1, 2, 3 };
    CHECK(vis_plane_init(&p, nx, py, wx, wy, 0) == DZ_EINVAL);
    CHECK(vis_selftest() == DZ_OK);
}

/* accel_ff：从 2026H ball.c 提取；ref 为提取前的原公式，逐点对比保证行为不变 */
#include "accel_ff.h"
static float aff_ref(float a, float gain, float dead, float fail, float mx)
{
    float y;
    if (gain == 0.0f) return 0.0f;
    if (!(a == a) || fabsf(a) > fail) return 0.0f;
    if (fabsf(a) < dead) return 0.0f;
    a -= a > 0.0f ? dead : -dead;
    y = a / 9.80665f * 57.29578f * gain;
    return y > mx ? mx : (y < -mx ? -mx : y);
}
TEST(accel_ff_basic)
{
    accel_ff_cfg_t c = { 1.0f, 0.15f, 8.0f, 5.0f };
    CHECK(accel_ff_selftest() == DZ_OK);
    CHECK_NEAR(accel_ff_deg(&c, 0.1f, true), 0.0f, 1e-6);          /* 死区内 */
    CHECK_NEAR(accel_ff_deg(&c, 0.1500001f, true), 0.0f, 1e-4);    /* 边沿连续 */
    CHECK_NEAR(accel_ff_deg(&c, 9.0f, true), 0.0f, 1e-6);          /* 超限 → 0 */
    CHECK_NEAR(accel_ff_deg(&c, NAN, true), 0.0f, 1e-6);
    CHECK_NEAR(accel_ff_deg(&c, 3.0f, false), 0.0f, 1e-6);         /* 无效 → 0 */
    CHECK_NEAR(accel_ff_deg(&c, 7.0f, true), 5.0f, 1e-6);          /* 限幅 */
    CHECK_NEAR(accel_ff_deg(&c, -7.0f, true), -5.0f, 1e-6);
    c.gain = 0.0f; CHECK_NEAR(accel_ff_deg(&c, 3.0f, true), 0.0f, 1e-6);
}
TEST(accel_ff_matches_legacy)
{
    const float gains[] = { 0.0f, 0.5f, 1.3f, 3.0f };
    int gi; float a;
    for (gi = 0; gi < 4; ++gi)
        for (a = -12.0f; a <= 12.0f; a += 0.01f) {
            accel_ff_cfg_t c = { gains[gi], 0.15f, 8.0f, 5.0f };
            CHECK_NEAR(accel_ff_deg(&c, a, true), aff_ref(a, gains[gi], 0.15f, 8.0f, 5.0f), 1e-6);
        }
}

/* stall：一阶电机模型 w' = (k·u − w)/tau，电流 i = (u − w/k)/R（反电动势）；卡轴时 w=0 */
#include "stall.h"
static stall_state_t stall_run(stall_t *s, float lock_at_s, float u, float *t_hit)
{
    float w = 0.0f; stall_state_t st = STALL_NORMAL; *t_hit = -1.0f;
    for (uint32_t ms = 0; ms < 3000u; ms++) {
        float t = (float)ms * 1e-3f;
        bool locked = lock_at_s >= 0.0f && t >= lock_at_s;
        if (locked) w = 0.0f; else w += 1e-3f * (10.0f * u - w) / 0.05f;     /* k=10 rad/s/V，tau=50 ms */
        float i = (u - w / 10.0f) / 0.5f;                                       /* R=0.5 Ω：起步浪涌 2·u A，稳态≈0 */
        st = stall_update(s, i, w, ms);
        if (st == STALL_STALLED && *t_hit < 0.0f) *t_hit = t;
    }
    return st;
}

TEST(stall_detect_model)
{
    CHECK(stall_selftest() == DZ_OK);
    stall_cfg_t c = { 1.0f, 0.5f, 200u, 150u, 0u };   /* 1 A、0.5 rad/s、200 ms、起步豁免 150 ms */
    stall_t s; float th;
    CHECK(stall_init(&s, &c) == DZ_OK);
    CHECK(stall_run(&s, -1.0f, 1.0f, &th) == STALL_NORMAL && s.count == 0u);          /* 正常起步：浪涌 2 A 但很快转起来 */
    CHECK(stall_init(&s, &c) == DZ_OK);
    CHECK(stall_run(&s, 1.0f, 1.0f, &th) == STALL_STALLED);                            /* 1 s 时卡住轴 */
    CHECK(th > 1.149f && th < 1.352f);                                                 /* 豁免 + 持续之后才报 */
    CHECK(stall_init(&s, &c) == DZ_OK);
    CHECK(stall_run(&s, 0.0f, 1.0f, &th) == STALL_STALLED && th >= 0.349f && th <= 0.352f); /* 一上电就卡住：豁免 150 + 持续 200 */
    CHECK(stall_update(&s, 0.0f, 0.0f, 4000u) == STALL_STALLED);                       /* 锁存：负载降了也不自动解除 */
    stall_clear(&s); CHECK(stall_update(&s, 0.0f, 0.0f, 4001u) == STALL_NORMAL);
    stall_cfg_t r = c; r.retry_ms = 500u; CHECK(stall_init(&s, &r) == DZ_OK);
    for (uint32_t ms = 0; ms <= 400u; ms++) (void)stall_update(&s, 2.0f, 0.0f, ms);
    CHECK(s.st == STALL_STALLED && s.count == 1u);
    CHECK(stall_update(&s, 2.0f, 0.0f, 600u) == STALL_STALLED);                        /* 还没到重试 */
    CHECK(stall_update(&s, 2.0f, 0.0f, 900u) == STALL_NORMAL);                         /* 重试：重新豁免 */
    for (uint32_t ms = 901u; ms <= 1300u; ms++) (void)stall_update(&s, 2.0f, 0.0f, ms);
    CHECK(s.st == STALL_STALLED && s.count == 2u);                                     /* 还堵：再锁 */
    CHECK(stall_init(&s, &c) == DZ_OK);
    for (uint32_t ms = 0; ms <= 1000u; ms++) (void)stall_update(&s, NAN, 0.0f, ms);
    CHECK(s.st == STALL_NORMAL);                                                       /* NaN 不误报 */
    stall_cfg_t bad = c; bad.hold_ms = 0u; CHECK(stall_init(&s, &bad) == DZ_EINVAL);
    bad = c; bad.load_on = -1.0f; CHECK(stall_init(&s, &bad) == DZ_EINVAL);
}

/* line_obs：横向偏差模型 pos' = drift − k·steer（mm/拍），传感器量程 ±40 mm，超出看不到线 */
#include "line_obs.h"
static int line_obs_run(bool search, uint32_t *lost_n)
{
    line_obs_t o; line_obs_cfg_t c = line_obs_cfg_default();
    float pos = 0.0f;
    line_obs_state_t st = LINE_OBS_TRACK;
    (void)line_obs_init(&o, &c);
    for (uint32_t ms = 0; ms < 20000u && st != LINE_OBS_FAIL; ms += 10u) {
        float drift = (ms >= 1000u && ms < 1300u) ? 2.0f : 0.0f;        /* 急弯：0.3 s 内线甩出去 */
        bool seen = fabsf(pos) < 40.0f;
        float steer;
        st = line_obs_update(&o, seen, pos, false, ms);
        if (st == LINE_OBS_TRACK) steer = 0.02f * pos;
        else steer = search ? (float)line_obs_dir(&o) * 1.5f : 0.0f;
        pos += drift - steer;
    }
    *lost_n = o.lost_count;
    return (int)st;
}

TEST(line_obs_recover_and_timeout)
{
    uint32_t n;
    CHECK(line_obs_selftest() == DZ_OK);
    CHECK(line_obs_run(true, &n) == LINE_OBS_TRACK && n == 1u);       /* 朝最后方向找回来 */
    CHECK(line_obs_run(false, &n) == LINE_OBS_FAIL && n == 1u);       /* 不找：12 s 后判失败停车 */
}

/* follow + peerlink：领车按 0.5 m/s 走，跟车从 1.5 m 外起步；中途断链 0.5 s 再恢复；末尾领车中止 */
#include "follow.h"
#include "peerlink.h"
TEST(follow_two_car_link)
{
    CHECK(follow_selftest() == DZ_OK && peerlink_selftest() == DZ_OK);
    follow_cfg_t c = { 0.5f, 0.2f, 1.2f, 0.3f, 1.0f, 1.5f, 3.0f };
    follow_t f; peer_rx_t r; dzframe_t fr;
    float s_lead = 1.5f, s_self = 0.0f, v_self = 0.0f, min_gap = 9.0f;
    uint8_t seq = 0;
    bool lost_seen = false;
    CHECK(follow_init(&f, &c) == DZ_OK);
    peer_rx_init(&r, 300u);
    for (uint32_t ms = 0; ms < 20000u; ms += 10u) {
        float v_lead = ms < 15000u ? 0.5f : 0.0f;
        s_lead += v_lead * 0.01f;
        bool radio_up = !(ms >= 6000u && ms < 6500u);
        if (ms % 100u == 0u && radio_up) {                             /* 10 Hz 时隙 */
            peer_state_t ps = { ms, s_lead, v_lead, 0, 0, 0, PEER_F_RUNNING };
            peerlink_state_frame(&ps, &fr); fr.seq = seq++;
            (void)peer_rx_feed(&r, &fr, ms);
        }
        if (ms == 18000u) { peerlink_abort_frame(1u, &fr); (void)peer_rx_feed(&r, &fr, ms); }
        bool ok = peer_rx_fresh(&r, ms);
        /* 对方里程按收到后的时间外推（帧 10 Hz，控制 100 Hz） */
        float gap = r.last.s_m + r.last.v_mps * (float)peer_rx_age_ms(&r, ms) * 1e-3f - s_self;
        v_self = follow_step(&f, ok, gap, r.last.v_mps, v_self, 0.01f);
        s_self += v_self * 0.01f;
        if (f.st == FOLLOW_LINK_LOST && ms > 6000u && ms < 7000u) lost_seen = true;
        if (ms == 5900u) CHECK(fabsf((s_lead - s_self) - 0.5f) < 0.05f);   /* 稳态间距 ≈ 0.5 m */
        if (ms > 1000u && s_lead - s_self < min_gap) min_gap = s_lead - s_self;
    }
    CHECK(lost_seen);                                                    /* 断链期间按 decel 减速 */
    CHECK(min_gap > 0.2f);                                               /* 全程没撞 */
    CHECK(v_self == 0.0f && f.st == FOLLOW_LINK_LOST && r.aborted);      /* 领车中止：停车锁存 */
}

void suite_ctrlparts(void)
{
    RUN(stall_detect_model);
    RUN(slew_dir_and_mag); RUN(slew_edge_cases); RUN(slew_with_motor_model);
    RUN(mtspeed_low_speed_vs_m_method); RUN(mtspeed_decel_timeout_reverse_wrap);
    RUN(vis_plane_five_point);
    RUN(line_obs_recover_and_timeout); RUN(follow_two_car_link); RUN(accel_ff_basic); RUN(accel_ff_matches_legacy);
}
