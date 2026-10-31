/**
 * @file app_main.c
 * @brief 两轮差速小车底盘（验收“只改引脚”）：本文件只用逻辑资源名 RES_*，没有任何引脚号、芯片型号、HAL/DriverLib 调用。
 *
 *  - CTRL 定时器 1 kHz（中断）：读两个编码器 -> 两个速度 PID -> 两个电机
 *  - 主循环：subsys 调度 drive_plan（10 ms，指令 -> 轮速目标，斜坡 + 超时停车）；
 *            每 20 ms 通过 LINK 发 dzframe 遥测帧；解析 LINK 收到的 dzframe 指令帧
 *
 * LINK 协议（dzframe/1，见 firmware/proto/dzframe）：
 *   上位机 -> 板  DATA id=1  payload: f32 v_mps, f32 w_rps     速度指令（≥5 Hz 持续发送，断线 200 ms 自动停车）
 *   板 -> 上位机  DATA id=2  payload: u32 ms, f32 sp_a, f32 spd_a, f32 sp_b, f32 spd_b, u32 ctrl_err
 *   板 -> 上位机  HEARTBEAT  每 500 ms（带 schema 哈希）
 *   参数读写 / 急停 / 命令：dzctl（firmware/proto/dzctl），字段与参数表见 app.yaml 的 link: 段（自动生成 link_gen.h）。
 *   急停锁存：电机刹车、忽略速度指令，直到收到命令 'R'。
 *   安全（framework/safety）：
 *     堵转：默认负载 = PID 输出占空比，|占空比| ≥ stall_duty 且 |转速| ≤ 0.2 rps 持续 stall_ms → 锁急停（心跳 STALL）。
 *       可选电流采样：board.yaml 有 ADC ISENSE_A/ISENSE_B 且参数 stall_src=1 时负载 = 电流（A），门限 stall_amp；默认关。
 *     安全态：上次复位原因是看门狗/内核锁死 → 上电锁急停（心跳 SAFE_BOOT），人看过原因发 'R' 才动。
 *     黑匣子（RAM 环 32 条）：复位原因、堵转、解除；上位机发 DATA id=0x7D len=0 导出。
 *   可选外设（car_aux.c）：板子有 VBAT 就监测电池（过放 → 急停），有 US_TRIG/US_ECHO 就测前方距离（太近 → 不许前进）。
 */
#include <string.h>
#include "board_gen.h"
#include "link_io.h"
#include "app.h"
#include "pid.h"
#include "motor_dc.h"
#include "encoder.h"
#include "dzframe.h"
#include "dzctl.h"
#include "link_relay.h"
#include "link_gen.h"
#include "subsys.h"
#include "drive_plan.h"
#include "car_aux.h"
#include "safety.h"
#include "blackbox.h"
#include "persist.h"
#include "dz_runtime.h"
#include "dz_compiler.h"
#include "nvm_pal.h"

/* ---- 机械参数：换电机/轮子改这里 ---- */
#define CTRL_PERIOD_US   1000u
#define COUNTS_PER_REV   1560.0f   /* 【未验证】轮子转一圈的累计计数（PAL 的硬件正交/软件解码均为 4 倍频）。
                                        * 两车同款电机，旧代码约 3.7 倍的 ticks/m 差异疑为倍频/单位换算错误；
                                        * 按 docs/12-参考工程与参数来源.md 的“转 10 圈”标定后填写。 */
#define ID_CMD   1u
#define WDG_MS   500u   /* 独立看门狗：主循环卡住 500 ms 硬件复位（主循环最坏约几 ms；改这里要同步 app.yaml protect_fixed） */

typedef struct { motor_dc_t motor; encoder_t enc; pid_ctrl_t pid; } wheel_t;
#define STALL_SPEED_RPS 0.2f   /* “转速近零”：编码器噪声之上、正常最低巡航（约 0.04 m/s）之下 */

static wheel_t s_w[2];
static car_state_t s_state;
static subsys_sched_t s_sched;
static dzframe_parser_t s_rx;
static volatile float s_sp[2];
static volatile uint32_t s_ctrl_errors;
static drive_params_t s_params = { .wheel_diam_m = 0.065f, .track_m = 0.15f };   /* 其余字段来自 g_link_params */
static volatile bool s_estop;
static volatile bool s_gains_dirty;
static safety_t s_safe;
static bb_t s_bb;
static bb_rec_t s_bb_ring[32];
/* 掉电保存（板子 board.yaml mcu.nvm_kb > 0 才有；没有/坏了 → 全部照常跑，只是不保存） */
/* flash 键见 dz_runtime.h（参数 / 黑匣子 DZRT_KEY_BB / 运行模式）；自检、存参、运行模式由通用运行时处理 */
#define CAR_EV_SELFTEST (BB_EV_APP + 0x10u)   /* 上电自检：arg = 失败项数 */
static dzrt_t s_rt;
static persist_kvbb_t s_kvbb;
static bb_store_t s_bbst;
static bool s_have_kv;
#if defined(RES_ADC_ISENSE_A) && defined(RES_ADC_ISENSE_B)
#define HAVE_ISENSE 1
static volatile float s_amp[2];   /* 主循环采样换算（ADC 不放进 1 kHz 中断） */
#else
#define HAVE_ISENSE 0
#endif
static bool use_current(void) { return HAVE_ISENSE && g_link_params.stall_src == 1u; }
static dzctl_wd_t s_wd;   /* 上位机心跳看门狗：调参时上位机崩溃/拔线 -> 输出归零并锁存急停 */

/* 上位机改了参数：同步到 drive_plan 参数；PID 增益交给控制中断在自己的节拍里换（不在两次 update 之间撕裂）。 */
static void apply_params(void)
{
    s_params.max_rps = g_link_params.max_rps;
    s_params.accel_rps2 = g_link_params.accel_rps2;
    s_params.cmd_timeout_ms = g_link_params.cmd_timeout_ms;
    s_gains_dirty = true;
    /* 门限只改数值不改状态：调参不会把已锁存的堵转清掉 */
    safety_set_stall(&s_safe, use_current() ? g_link_params.stall_amp : g_link_params.stall_duty, g_link_params.stall_ms);
}

static void ctrl_isr(void *ctx)
{
    static uint32_t last_us;
    uint32_t now_us = pal_micros();
    float dt_s = (float)(now_us - last_us) * 1e-6f;   /* 断点调试恢复 / 中断被长时间屏蔽后，dt 会异常大 */
    (void)ctx;
    last_us = now_us;
    for (unsigned i = 0; i < 2; i++) {
        wheel_t *w = &s_w[i];
        (void)pid_check_gap(&w->pid, dt_s);           /* 异常就清微分历史，不在恢复那拍打出 D 冲击 */
        if (s_gains_dirty) (void)pid_set_gains(&w->pid, g_link_params.kp, g_link_params.ki, 0.0f);
        /* 急停时也要更新编码器：否则遥测里的转速冻结在急停前的值，上位机看着像还在转 */
        dz_err_t ee = encoder_update(&w->enc);
        if (s_estop) { motor_dc_stop(&w->motor, MOTOR_DC_BRAKE); pid_reset(&w->pid); continue; }
        if (ee != DZ_OK) { s_ctrl_errors++; motor_dc_stop(&w->motor, MOTOR_DC_COAST); continue; }
        float spd = encoder_speed_rps(&w->enc), u = pid_update(&w->pid, s_sp[i], spd);
#if HAVE_ISENSE
        float load = use_current() ? s_amp[i] : u;
#else
        float load = u;
#endif
        if (safety_update(&s_safe, (uint8_t)i, load, spd, pal_millis())) { motor_dc_stop(&w->motor, MOTOR_DC_BRAKE); continue; }
        if (motor_dc_set(&w->motor, u) != DZ_OK) s_ctrl_errors++;
    }
    s_gains_dirty = false;
}

static dz_err_t wheel_init(wheel_t *w, pal_id_t pwm, pal_id_t in1, pal_id_t in2, pal_id_t enc)
{
    dz_err_t e;
    motor_dc_cfg_t mc = motor_dc_cfg_default();
    mc.mode = MOTOR_DC_PWM_IN1_IN2;
    mc.pwm = pwm; mc.in1 = in1; mc.in2 = in2;
    mc.max_duty = 0.9f;
    if ((e = motor_dc_init(&w->motor, &mc)) != DZ_OK) return e;

    encoder_cfg_t ec = encoder_cfg_default();
    ec.enc = enc;
    ec.counts_per_rev = COUNTS_PER_REV;
    ec.dt_s = CTRL_PERIOD_US * 1e-6f;
    ec.speed_lpf_hz = 50.0f;
    if ((e = encoder_init(&w->enc, &ec)) != DZ_OK) return e;

    pid_cfg_t pc = pid_cfg_default(CTRL_PERIOD_US * 1e-6f);
    pc.kp = g_link_params.kp; pc.ki = g_link_params.ki; pc.kd = 0.0f;   /* 起步参数见 app.yaml，未实测 */
    pc.out_min = -1.0f; pc.out_max = 1.0f;
    pc.i_min = -1.0f; pc.i_max = 1.0f;
    pc.out_rate_max = 20.0f;
    return pid_init(&w->pid, &pc);
}

static bool car_still(void)
{
    float sa = encoder_speed_rps(&s_w[0].enc), sb = encoder_speed_rps(&s_w[1].enc);
    return s_estop || (s_state.cmd_v_mps == 0.0f && s_state.cmd_w_rps == 0.0f && sa * sa + sb * sb < 0.01f);
}

static subsys_sched_t *s_sched_p;
static bool st_subsys(void) { return subsys_sched_selftest(s_sched_p) < 0; }   /* 应用自己的自检项：drive_plan 子系统 */

static void send(const dzframe_t *f);

dz_err_t app_init(void)
{
    static const subsys_t *const list[] = { &g_drive_plan };
    dz_err_t e;
    bool bad_boot = false;
    pal_reset_cause_t rc = pal_reset_cause();
    dzctl_estop_clear();        /* 上电：RAM 里的旧原因不算（仿真里 app_init 会重跑） */
    uint16_t pl = dzrt_boot(&s_rt, &g_link_params, &g_link_params_default, car_still, send);   /* 先读参数：下面的堵转配置要用 */
    s_have_kv = s_rt.have_kv && persist_kv_bb_store(&s_bbst, &s_kvbb, &s_rt.kv, DZRT_KEY_BB) == DZ_OK;
    stall_cfg_t sc = { .load_on = g_link_params.stall_duty, .speed_on = STALL_SPEED_RPS,
                       .hold_ms = g_link_params.stall_ms, .start_ignore_ms = 200u, .retry_ms = 0u };   /* 只人工解除 */
    (void)bb_init(&s_bb, s_bb_ring, (uint16_t)(sizeof s_bb_ring / sizeof s_bb_ring[0]), s_have_kv ? &s_bbst : NULL);
    if (s_have_kv) {   /* 上次急停/堵转时冻结的记录放回环里（在本次“上电”之前），上位机导出一起看到 */
        static bb_rec_t prev[15];
        uint16_t n = 0;
        if (bb_load_frozen(&s_bb, prev, (uint16_t)(sizeof prev / sizeof prev[0]), &n) == DZ_OK && n) {
            bb_log(&s_bb, 0u, BB_EV_FROZEN, n, 0.0f, 0.0f);
            for (uint16_t k = 0; k < n; k++) bb_log(&s_bb, prev[k].t_ms, prev[k].code, prev[k].arg, prev[k].a, prev[k].b);
        }
    }
    if ((e = safety_init(&s_safe, &sc, 2u, &s_bb)) != DZ_OK) return e;
    dzctl_set_reset_cause((uint32_t)rc);
    if (safety_boot(&s_safe, (uint32_t)rc, PAL_RESET_IS_FAULT(rc), pal_millis())) {   /* 卡死过：等人看 */
        s_estop = true;
        dzctl_estop_note(DZCTL_ES_SAFE_BOOT, pal_millis(), (float)(uint32_t)rc);
    }   /* 卡死过：等人看 */
    bb_log(&s_bb, pal_millis(), BB_EV_PARAM_LOAD, pl, 0.0f, 0.0f);
    apply_params();
    if ((e = wheel_init(&s_w[0], RES_PWM_MOTOR_A, RES_GPIO_MOTOR_A_IN1, RES_GPIO_MOTOR_A_IN2, RES_ENCODER_MOTOR_A)) != DZ_OK) return e;
    if ((e = wheel_init(&s_w[1], RES_PWM_MOTOR_B, RES_GPIO_MOTOR_B_IN1, RES_GPIO_MOTOR_B_IN2, RES_ENCODER_MOTOR_B)) != DZ_OK) return e;
    if ((e = subsys_sched_init(&s_sched, list, 1, &s_state, &s_params)) != DZ_OK) return e;
    s_rt.bb = &s_bb;
    s_sched_p = &s_sched;
    (void)dzctl_selftest_register(DZCTL_ST_SUBSYS, st_subsys);
    {   /* 上电自检（通用运行时 + 本应用注册的项）：不过也不罢工（上位机要能看到为什么），而是急停锁存 + 心跳标志 + 原因 */
        uint32_t mask = dzrt_selftest(&s_rt, pal_millis());
        int bad = 0;
        for (uint32_t m = mask; m; m &= m - 1u) bad++;
        bad_boot = bad != 0 || s_estop;
        if (bad) { s_estop = true; dzctl_estop_note(DZCTL_ES_SELFTEST, pal_millis(), (float)bad); }
        bb_log(&s_bb, pal_millis(), CAR_EV_SELFTEST, (uint16_t)bad, 0.0f, 0.0f);
    }
    dzrt_start(&s_rt, !bad_boot, g_link_params.sa_autostart != 0u);
    subsys_sched_set_mode(&s_sched, SUBSYS_MODE_RUN);
    dzframe_parser_init(&s_rx);
    dzctl_wd_init(&s_wd, 1000u);   /* 侧车每 250 ms 发一次心跳 */
    if ((e = car_aux_init()) != DZ_OK) return e;
    if ((e = pal_timer_start(RES_TIMER_CTRL, CTRL_PERIOD_US, ctrl_isr, 0)) != DZ_OK) return e;
    e = pal_wdg_start(WDG_MS);           /* 最后开：初始化慢不会被咬。ENOTSUP（如 MSPM0 未实现）照常运行 */
    return e == DZ_ENOTSUP ? DZ_OK : e;
}

static void send(const dzframe_t *f)
{
    uint8_t out[DZFRAME_MAX_FRAME];
    size_t n = dzframe_encode(out, sizeof out, f);
    if (n) (void)link_write(out, (uint16_t)n);   /* EBUSY 时丢这一帧，下一帧补上 */
}

static uint8_t s_relay_seq;

/* 仅 host-sim：sim_setup.c 覆盖，'K' n = 模拟按住板上按键 n×100 ms（测短按启动 / 长按切模式）；真板为空 */
DZ_WEAK void car_sim_key(uint8_t n);
DZ_WEAK void car_sim_key(uint8_t n) { (void)n; }

static void handle_rx(uint32_t now)
{
    uint8_t buf[32]; uint16_t got = 0;
    if (link_read(buf, sizeof buf, &got) != DZ_OK) return;
    dzframe_t f, ack;
    dzctl_table_t t = link_param_table(&g_link_params);
    for (uint16_t i = 0; i < got; i++) {
        if (!dzframe_feed(&s_rx, buf[i], &f)) continue;
        dzctl_wd_feed(&s_wd, &f, now);
        if (dzctl_is_estop(&f)) {
            s_estop = true;
            dzctl_estop_note(DZCTL_ES_MANUAL, now, 0.0f);
            s_state.cmd_v_mps = s_state.cmd_w_rps = 0.0f;
        } else if (link_relay_frame(&f, s_estop, &s_relay_seq, &ack)) {
            send(&ack);
        } else if (dzctl_handle(&t, &f, &ack)) {
            apply_params();
            send(&ack);
        } else if (f.kind == DZF_DATA && f.id == DZCTL_ID_CMD && f.len >= 1u && f.payload[0] == 'R') {
            uint32_t st = pal_irq_save();
            s_estop = false;
            safety_clear(&s_safe, now);
            dzctl_estop_clear();
            pal_irq_restore(st);
        } else if (f.kind == DZF_DATA && f.id == DZCTL_ID_CMD && f.len >= 1u && f.payload[0] == 'K') {
            car_sim_key(f.len >= 2u ? f.payload[1] : 1u);
        } else if (dzrt_cmd(&s_rt, &f)) {                       /* 'W' 'M' 'H'：主循环里执行 */
        } else if (f.kind == DZF_DATA && f.id == DZCTL_ID_CMD && f.len >= 1u && f.payload[0] == 'M') {
            dzrt_reply2(&s_rt, 'M', 4u);                         /* 缺确认字节：拒切也要回执 */
        } else if (dzctl_is_bb_request(&f)) {
            static uint8_t bseq;
            for (uint16_t k = 0; k < bb_count(&s_bb); k++) {
                const bb_rec_t *r = bb_get(&s_bb, k);
                dzctl_bb_frame(r->t_ms, r->code, r->arg, r->a, r->b, bseq++, &ack);
                send(&ack);
            }
        } else if (!s_estop && dzrt_needs_host(&s_rt) && f.kind == DZF_DATA && f.id == ID_CMD && f.len == 8u) {   /* 脱机：不收上位机目标 */
            s_state.cmd_v_mps = car_aux_limit_v(dzframe_get_f32(&f, 0));
            s_state.cmd_w_rps = dzframe_get_f32(&f, 4);
            s_state.cmd_ms = now;
        }
    }
}

void app_loop(void)
{
    static uint32_t last_tx, last_led;
    static uint32_t last_hb = 0u - 500u;   /* 复位后第一拍就发心跳（带 schema 哈希），上位机不用等 500 ms 才认出板子 */
    static uint8_t seq;
    uint32_t now = pal_millis();
    pal_wdg_kick();
    handle_rx(now);
    if (dzrt_needs_host(&s_rt) && dzctl_wd_expired(&s_wd, now)) { dzctl_estop_note(DZCTL_ES_HB_TIMEOUT, now, (float)(uint32_t)(now - s_wd.last_ms)); s_estop = true; s_state.cmd_v_mps = s_state.cmd_w_rps = 0.0f; }
    if (car_aux_poll(now)) { dzctl_estop_note(DZCTL_ES_UNDERVOLT, now, car_aux_vbat()); s_estop = true; s_state.cmd_v_mps = s_state.cmd_w_rps = 0.0f; }   /* 只置不清 */
    link_relay_guard(s_estop);   /* 急停（心跳超时/电池/安全锁存）中结束继电 */
#if HAVE_ISENSE
    {   /* 电流采样：引脚 mV（含分压）−零点 → ÷ mV/A；读失败当 0（不误判堵转），计 ctrl_err */
        static const pal_id_t ch[2] = { RES_ADC_ISENSE_A, RES_ADC_ISENSE_B };
        for (unsigned i = 0; i < 2; i++) {
            uint16_t raw; pal_adc_info_t in;
            if (pal_adc_read(ch[i], &raw) != DZ_OK || pal_adc_info(ch[i], &in) != DZ_OK || g_link_params.isense_mv_per_a <= 0.0f) { s_amp[i] = 0.0f; s_ctrl_errors++; continue; }
            float mv = (float)raw * (float)in.vref_mv / (float)((1u << in.bits) - 1u) * (float)in.scale_num / (float)in.scale_den;
            float a = (mv - g_link_params.isense_zero_mv) / g_link_params.isense_mv_per_a;
            s_amp[i] = a < 0.0f ? -a : a;
        }
    }
#endif
    if (safety_latched(&s_safe) && !s_estop) {
        dzctl_estop_note((safety_flags(&s_safe) & SAFETY_F_STALL) ? DZCTL_ES_STALL : DZCTL_ES_SAFE_BOOT, now,
                         (safety_flags(&s_safe) & SAFETY_F_STALL) ? g_link_params.stall_duty : (float)(uint32_t)pal_reset_cause());
        s_estop = true; s_state.cmd_v_mps = s_state.cmd_w_rps = 0.0f; }
    {   /* 进急停（电机已刹）那一刻把黑匣子冻进 flash：下次上电还能看到为什么停的；失败不影响别的 */
        static bool was;
        if (s_estop && !was && s_have_kv) (void)bb_freeze(&s_bb);
        was = s_estop;
    }
    {
        bool was_sa = !dzrt_needs_host(&s_rt);
        dzrt_poll(&s_rt, now, s_estop, -1);
        if (was_sa != !dzrt_needs_host(&s_rt)) dzctl_wd_init(&s_wd, 1000u);
    }
    if (!dzrt_needs_host(&s_rt)) {   /* 脱机：目标来自板上参数；急停时不动 */
        s_state.cmd_v_mps = dzrt_sa_running(&s_rt) ? g_link_params.sa_v_mps : 0.0f;
        s_state.cmd_w_rps = 0.0f;
        s_state.cmd_ms = now;
    }
    dzctl_set_flags(SAFETY_F_SAFE_BOOT | SAFETY_F_STALL, false);
    dzctl_set_flags(safety_flags(&s_safe), true);
    s_state.cmd_v_mps = car_aux_limit_v(s_state.cmd_v_mps);
    subsys_sched_poll(&s_sched, now);
    uint32_t st = pal_irq_save();
    if (s_estop) s_state.sp_a_rps = s_state.sp_b_rps = 0.0f;   /* 急停：轮速目标（含斜坡）立即归零，'R' 后从 0 起，遥测不报旧目标 */
    s_sp[0] = s_state.sp_a_rps; s_sp[1] = s_state.sp_b_rps;
    pal_irq_restore(st);

    if (now - last_tx >= LINK_TELEM_PERIOD_MS) {
        link_telem_t t;
        dzframe_t f;
        last_tx = now;
        st = pal_irq_save();
        t.t_ms = now; t.sp_a = s_sp[0]; t.sp_b = s_sp[1];
        t.spd_a = encoder_speed_rps(&s_w[0].enc); t.spd_b = encoder_speed_rps(&s_w[1].enc);
        t.ctrl_err = s_ctrl_errors;
        pal_irq_restore(st);
        if (link_telem_pack(&f, &t)) { f.seq = seq++; send(&f); }
    }
    static bool hb_was_estop;
    if (dzrt_hb_due(now, s_estop, &hb_was_estop, &last_hb)) {   /* 急停上升沿 / 下降沿立即发（与 link_app 同一个助手） */
        dzctl_table_t t = link_param_table(&g_link_params);
        dzframe_t f;
        dzctl_heartbeat(&t, seq++, &f);
        send(&f);
    }
#ifdef RES_GPIO_LED
    if (now - last_led >= 250u) { last_led = now; pal_gpio_toggle(RES_GPIO_LED); }
#else
    (void)last_led;
#endif
}
