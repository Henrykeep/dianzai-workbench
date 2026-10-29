/**
 * @file app_main.c
 * @brief 双车循线跟车（D 题式第二例题）。同一份固件，参数 role：0 前车 / 1 后车。
 *
 *   内环：1 kHz 两轮速度 PI（中断，同 apps/line_car）。
 *   外环 200 Hz：8 路灰度 → line_obs（丢线确认 / 找线 / 超时 FAIL）→ 线位置 PD 给两轮差速；
 *     前车：巡航 v_base；后车：follow_step(间距 = gap0 + 前车里程增量 − 自己里程) 出车速。
 *   两车链路 peerlink（PEER 串口，LoRa / 蓝牙透传）：每 peer_ms（默认 20 ms）发 STATE（里程、车速、RUNNING/STOPPED），
 *     收对方 STATE；超过 stale_ms 没帧 = 链路断 → 后车按 f_decel 减速到 0（follow 的 LINK_LOST）。
 *   安全（与 DS-land-and-air 联调规范同口径：本地先停车再发，不等确认）：
 *     本机急停（上位机 E / 看门狗）→ 立刻停 + 连发 3 帧 ABORT；收到对方 ABORT → 停车并锁存（mode ABORT），
 *     'C' 人工确认后解除；前车 STOPPED（丢线 FAIL / 急停）→ 后车当链路不可用减速停；间距 < gap_min → 立停。
 *     每次中止/链路断/太近/丢线记黑匣子。
 *   命令：'C' 解除中止锁存 + 复位找线；'Z' 两车里程重新对齐（后车以下一帧前车里程为起点，配合 gap0_m）。
 * Source: 安全口径参考 github.com/2026-nuedc-d-land-air/DS-land-and-air@0cec55c docs/D题_V23_联调与计分矩阵.md
 *         （用户确认可用，见 docs/参考来源.md）；代码为本仓库自写，复用 algo/line_obs、algo/follow、proto/peerlink。
 */
#include "board_gen.h"
#include "app.h"
#include "pid.h"
#include "motor_dc.h"
#include "encoder.h"
#include "line_sensor.h"
#include "link_app.h"
#include "line_obs.h"
#include "follow.h"
#include "peerlink.h"
#include "blackbox.h"

#define CTRL_PERIOD_US 1000u
#define COUNTS_PER_REV 1560.0f   /* 【未验证】同 line_car */
#define ABORT_ESTOP    1u        /* ABORT reason：对方急停 */

/* 应用黑匣子码 */
#define EV_PEER_ABORT  (BB_EV_APP + 1u)   /* arg 0 收到 / 1 发出；a = reason */
#define EV_LINK_LOST   (BB_EV_APP + 2u)   /* a = 链路断时的间距估计 */
#define EV_TOO_CLOSE   (BB_EV_APP + 3u)   /* a = 间距 */

enum { M_STOP = 0, M_RUN = 1, M_ESTOP = 2, M_SEARCH = 3, M_ABORT = 4 };

typedef struct { motor_dc_t m; encoder_t e; pid_ctrl_t pid; } wheel_t;
static wheel_t s_w[2];
static line_sensor_t s_line;
static link_app_t L;
static volatile float s_sp[2];
static volatile bool s_dirty = true;
static volatile uint8_t s_mode;
static float s_pos, s_last_pos;
static line_obs_t s_obs;
static follow_t s_fol;
static peer_rx_t s_peer;
static dzframe_parser_t s_pp;
static uint8_t s_peer_seq;
static float s_self, s_vself, s_vcmd, s_gap;
static float s_lead0; static bool s_have_lead0;
static bb_t s_bb;
static bb_rec_t s_bb_ring[24];

static void peer_send(const dzframe_t *f)
{
    uint8_t buf[DZFRAME_MAX_FRAME];
    dzframe_t g = *f;
    g.seq = s_peer_seq++;
    size_t n = dzframe_encode(buf, sizeof buf, &g);
    if (n) (void)pal_uart_write(RES_UART_PEER, buf, (uint16_t)n);
}

static void follow_cfg_apply(void)
{
    follow_cfg_t c;
    c.gap_ref_m = g_link_params.gap_ref_m; c.gap_min_m = g_link_params.gap_min_m;
    c.kp = g_link_params.f_kp; c.kd = g_link_params.f_kd;
    c.v_max = 1.3f * g_link_params.v_base; c.accel = 1.0f; c.decel = g_link_params.f_decel;
    float v = s_fol.v; follow_state_t st = s_fol.st;
    if (follow_init(&s_fol, &c) == DZ_OK) { s_fol.v = v; s_fol.st = st; }
}

static void on_cmd(uint8_t c, uint8_t n)
{
    (void)n;
    if (c == 'C') { peer_rx_clear_abort(&s_peer); line_obs_reset(&s_obs); }
    else if (c == 'Z') { s_self = 0.0f; s_have_lead0 = false; }
}

static void apply_params(void)
{
    s_dirty = true;
    follow_cfg_apply();
    s_peer.stale_ms = g_link_params.stale_ms;
}

static void ctrl_isr(void *ctx)
{
    static uint32_t last_us;
    uint32_t now = pal_micros();
    float dt = (float)(now - last_us) * 1e-6f;
    (void)ctx;
    last_us = now;
    for (unsigned i = 0; i < 2; i++) {
        wheel_t *w = &s_w[i];
        (void)pid_check_gap(&w->pid, dt);
        if (s_dirty) (void)pid_set_gains(&w->pid, g_link_params.kp, g_link_params.ki, 0.0f);
        (void)encoder_update(&w->e);
        if (L.estop || (s_mode != M_RUN && s_mode != M_SEARCH)) { motor_dc_stop(&w->m, MOTOR_DC_BRAKE); pid_reset(&w->pid); continue; }
        (void)motor_dc_set(&w->m, pid_update(&w->pid, s_sp[i], encoder_speed_rps(&w->e)));
    }
    s_dirty = false;
}

static dz_err_t wheel_init(wheel_t *w, pal_id_t pwm, pal_id_t in1, pal_id_t in2, pal_id_t enc)
{
    dz_err_t e;
    motor_dc_cfg_t mc = motor_dc_cfg_default();
    mc.mode = MOTOR_DC_PWM_IN1_IN2; mc.pwm = pwm; mc.in1 = in1; mc.in2 = in2; mc.max_duty = 0.95f;
    if ((e = motor_dc_init(&w->m, &mc)) != DZ_OK) return e;
    encoder_cfg_t ec = encoder_cfg_default();
    ec.enc = enc; ec.counts_per_rev = COUNTS_PER_REV; ec.dt_s = CTRL_PERIOD_US * 1e-6f; ec.speed_lpf_hz = 50.0f;
    if ((e = encoder_init(&w->e, &ec)) != DZ_OK) return e;
    pid_cfg_t pc = pid_cfg_default(CTRL_PERIOD_US * 1e-6f);
    pc.kp = g_link_params.kp; pc.ki = g_link_params.ki; pc.out_min = -1; pc.out_max = 1; pc.i_min = -1; pc.i_max = 1;
    return pid_init(&w->pid, &pc);
}

dz_err_t app_init(void)
{
    static const pal_id_t ids[8] = { RES_GPIO_LINE0, RES_GPIO_LINE1, RES_GPIO_LINE2, RES_GPIO_LINE3,
                                     RES_GPIO_LINE4, RES_GPIO_LINE5, RES_GPIO_LINE6, RES_GPIO_LINE7 };
    dz_err_t e;
    if ((e = wheel_init(&s_w[0], RES_PWM_MOTOR_A, RES_GPIO_MOTOR_A_IN1, RES_GPIO_MOTOR_A_IN2, RES_ENCODER_MOTOR_A)) != DZ_OK) return e;
    if ((e = wheel_init(&s_w[1], RES_PWM_MOTOR_B, RES_GPIO_MOTOR_B_IN1, RES_GPIO_MOTOR_B_IN2, RES_ENCODER_MOTOR_B)) != DZ_OK) return e;
    line_cfg_t lc = line_cfg_default();
    lc.n = 8; lc.pitch_mm = 12.0f;
    for (unsigned i = 0; i < 8; i++) lc.ids[i] = ids[i];
    if ((e = line_init(&s_line, &lc)) != DZ_OK) return e;
    line_obs_cfg_t oc = line_obs_cfg_default();
    oc.center_band = 6.0f;
    if ((e = line_obs_init(&s_obs, &oc)) != DZ_OK) return e;
    follow_cfg_apply();
    if (s_fol.c.decel <= 0.0f) return DZ_EINVAL;               /* follow_init 拒了参数：不带病跑 */
    peer_rx_init(&s_peer, g_link_params.stale_ms);
    dzframe_parser_init(&s_pp);
    (void)bb_init(&s_bb, s_bb_ring, (uint16_t)(sizeof s_bb_ring / sizeof s_bb_ring[0]), NULL);
    bb_log(&s_bb, pal_millis(), BB_EV_RESET, 0, 0.0f, 0.0f);
    link_app_init(&L, apply_params, on_cmd);
    L.bb = &s_bb;
    return pal_timer_start(RES_TIMER_CTRL, CTRL_PERIOD_US, ctrl_isr, 0);
}

static void peer_poll(uint32_t now)
{
    uint8_t buf[64]; uint16_t got = 0;
    dzframe_t f;
    bool was_ab = s_peer.aborted;
    while (pal_uart_read(RES_UART_PEER, buf, sizeof buf, &got) == DZ_OK && got) {
        for (uint16_t i = 0; i < got; i++)
            if (dzframe_feed(&s_pp, buf[i], &f)) (void)peer_rx_feed(&s_peer, &f, now);
    }
    if (s_peer.aborted && !was_ab) bb_log(&s_bb, now, EV_PEER_ABORT, 0, (float)s_peer.abort_reason, s_gap);
}

/** 外环一拍：返回两轮目标 rps。 */
static void outer(uint32_t now, float dt)
{
    const float circ = g_link_params.wheel_circ_m;
    line_result_t r;
    float va = 0.0f, vb = 0.0f;
    s_vself = 0.5f * (encoder_speed_rps(&s_w[0].e) + encoder_speed_rps(&s_w[1].e)) * circ;
    s_self += s_vself * dt;
    if (line_read(&s_line, &r) != DZ_OK) return;
    bool seen = !(r.flags & LINE_F_LOST);
    line_obs_state_t os0 = s_obs.st, os = line_obs_update(&s_obs, seen, r.pos_mm, (r.flags & LINE_F_CROSS) != 0u, now);
    if (line_obs_just_lost(&s_obs)) bb_log(&s_bb, now, BB_EV_LINE_LOST, (uint16_t)LINE_OBS_LOST, s_pos, (float)s_obs.lost_count);
    if (os == LINE_OBS_FAIL && os0 != LINE_OBS_FAIL) bb_log(&s_bb, now, BB_EV_LINE_LOST, (uint16_t)LINE_OBS_FAIL, s_pos, (float)s_obs.lost_count);

    /* 车速：前车巡航；后车跟车（链路/前车状态不好 → follow 内部减速到 0） */
    bool fresh = peer_rx_fresh(&s_peer, now);
    float v;
    if (g_link_params.role == 0u) { v = g_link_params.v_base; s_gap = 0.0f; }
    else {
        bool lead_ok = fresh && !(s_peer.last.flags & PEER_F_STOPPED);
        if (fresh && !s_have_lead0) { s_lead0 = s_peer.last.s_m; s_have_lead0 = true; }
        if (s_have_lead0) s_gap = g_link_params.gap0_m + (s_peer.last.s_m - s_lead0) - s_self;
        follow_state_t st0 = s_fol.st;
        v = follow_step(&s_fol, lead_ok && s_have_lead0, s_gap, s_peer.last.v_mps, s_vself, dt);
        if (s_fol.st != st0 && s_fol.st == FOLLOW_LINK_LOST) bb_log(&s_bb, now, EV_LINK_LOST, 0, s_gap, (float)peer_rx_age_ms(&s_peer, now));
        if (s_fol.st != st0 && s_fol.st == FOLLOW_TOO_CLOSE) bb_log(&s_bb, now, EV_TOO_CLOSE, 0, s_gap, s_vself);
    }
    s_vcmd = v;

    if (L.estop) s_mode = M_ESTOP;
    else if (s_peer.aborted) s_mode = M_ABORT;
    else if (os == LINE_OBS_FAIL) s_mode = M_STOP;
    else if (os == LINE_OBS_LOST) {                             /* 原地找线（同 line_car 1.1.0） */
        static uint32_t seg_t0; static uint8_t seg_k; static int8_t sweep;
        float vs = g_link_params.v_search / circ;
        int8_t d = line_obs_dir(&s_obs);
        s_mode = M_SEARCH;
        if (line_obs_just_lost(&s_obs)) { seg_t0 = now; seg_k = 1u; sweep = 1; }
        if (d == 0) {
            if ((uint32_t)(now - seg_t0) >= 300u * seg_k) { seg_t0 = now; seg_k = (uint8_t)(seg_k + (seg_k < 40u)); sweep = (int8_t)-sweep; }
            d = sweep;
        }
        s_pos = r.pos_mm;
        va = (float)d * vs; vb = -(float)d * vs;
    } else {
        s_mode = M_RUN;
        s_pos = r.pos_mm;
        float dw = g_link_params.kp_line * s_pos + g_link_params.kd_line * (s_pos - s_last_pos) / dt;
        s_last_pos = s_pos;
        float w = v / circ;
        if (v < 0.01f) dw = 0.0f;                               /* 停着不原地扭（PD 只在走的时候转向） */
        else if (g_link_params.v_base > 0.0f && v < g_link_params.v_base) dw *= v / g_link_params.v_base;
        va = w + dw; vb = w - dw;
    }
    uint32_t st = pal_irq_save();
    s_sp[0] = va; s_sp[1] = vb;
    pal_irq_restore(st);
}

void app_loop(void)
{
    static uint32_t last_ctl, last_tx;
    static bool was_estop;
    uint32_t now = pal_millis();
    peer_poll(now);
    if (L.estop && !was_estop) {                                /* 本地先停（中断里已经读 L.estop），再连发 3 帧 */
        dzframe_t f;
        peerlink_abort_frame(ABORT_ESTOP, &f);
        for (int i = 0; i < 3; i++) peer_send(&f);
        bb_log(&s_bb, now, EV_PEER_ABORT, 1, (float)ABORT_ESTOP, s_gap);
    }
    was_estop = L.estop;
    if (now - last_ctl >= 5u) {
        float dt = (float)(now - last_ctl) * 1e-3f;
        last_ctl = now;
        outer(now, dt);
    }
    if (now - last_tx >= g_link_params.peer_ms) {
        last_tx = now;
        peer_state_t ps = { 0 };
        dzframe_t f;
        ps.t_ms = now; ps.s_m = s_self; ps.v_mps = s_vself;
        ps.flags = (uint16_t)((s_mode == M_RUN || s_mode == M_SEARCH) ? PEER_F_RUNNING : PEER_F_STOPPED);
        peerlink_state_frame(&ps, &f);
        peer_send(&f);
    }
    if (!link_app_poll(&L, now)) return;
    link_telem_t t = { 0 };
    t.t_ms = now; t.mode = s_mode; t.fstate = (uint8_t)s_fol.st;
    t.gap_sp_m = g_link_params.gap_ref_m; t.gap_m = s_gap; t.v_cmd = s_vcmd; t.v_self = s_vself;
    t.v_lead = s_peer.last.v_mps; t.s_self = s_self; t.line_mm = s_pos;
    t.peer_age_ms = s_peer.have ? peer_rx_age_ms(&s_peer, now) : 0xFFFFFFFFu;
    t.peer_drop = s_peer.dup_ooo + s_peer.bad_len;
    link_app_send_telem(&L, &t);
}
