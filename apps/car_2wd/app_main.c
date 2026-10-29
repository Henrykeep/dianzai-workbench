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
 *   可选外设（car_aux.c）：板子有 VBAT 就监测电池（过放 → 急停），有 US_TRIG/US_ECHO 就测前方距离（太近 → 不许前进）。
 */
#include "board_gen.h"
#include "link_io.h"
#include "app.h"
#include "pid.h"
#include "motor_dc.h"
#include "encoder.h"
#include "dzframe.h"
#include "dzctl.h"
#include "link_gen.h"
#include "subsys.h"
#include "drive_plan.h"
#include "car_aux.h"

/* ---- 机械参数：换电机/轮子改这里 ---- */
#define CTRL_PERIOD_US   1000u
#define COUNTS_PER_REV   1560.0f   /* 【未验证】轮子转一圈的累计计数（PAL 的硬件正交/软件解码均为 4 倍频）。
                                        * 两车同款电机，旧代码约 3.7 倍的 ticks/m 差异疑为倍频/单位换算错误；
                                        * 按 docs/12-参考工程与参数来源.md 的“转 10 圈”标定后填写。 */
#define ID_CMD   1u

typedef struct { motor_dc_t motor; encoder_t enc; pid_ctrl_t pid; } wheel_t;

static wheel_t s_w[2];
static car_state_t s_state;
static subsys_sched_t s_sched;
static dzframe_parser_t s_rx;
static volatile float s_sp[2];
static volatile uint32_t s_ctrl_errors;
static drive_params_t s_params = { .wheel_diam_m = 0.065f, .track_m = 0.15f };   /* 其余字段来自 g_link_params */
static volatile bool s_estop;
static volatile bool s_gains_dirty;
static dzctl_wd_t s_wd;   /* 上位机心跳看门狗：调参时上位机崩溃/拔线 -> 输出归零并锁存急停 */

/* 上位机改了参数：同步到 drive_plan 参数；PID 增益交给控制中断在自己的节拍里换（不在两次 update 之间撕裂）。 */
static void apply_params(void)
{
    s_params.max_rps = g_link_params.max_rps;
    s_params.accel_rps2 = g_link_params.accel_rps2;
    s_params.cmd_timeout_ms = g_link_params.cmd_timeout_ms;
    s_gains_dirty = true;
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
        if (motor_dc_set(&w->motor, pid_update(&w->pid, s_sp[i], encoder_speed_rps(&w->enc))) != DZ_OK) s_ctrl_errors++;
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

dz_err_t app_init(void)
{
    static const subsys_t *const list[] = { &g_drive_plan };
    dz_err_t e;
    apply_params();
    if ((e = wheel_init(&s_w[0], RES_PWM_MOTOR_A, RES_GPIO_MOTOR_A_IN1, RES_GPIO_MOTOR_A_IN2, RES_ENCODER_MOTOR_A)) != DZ_OK) return e;
    if ((e = wheel_init(&s_w[1], RES_PWM_MOTOR_B, RES_GPIO_MOTOR_B_IN1, RES_GPIO_MOTOR_B_IN2, RES_ENCODER_MOTOR_B)) != DZ_OK) return e;
    if ((e = subsys_sched_init(&s_sched, list, 1, &s_state, &s_params)) != DZ_OK) return e;
    if (subsys_sched_selftest(&s_sched) >= 0) return DZ_EIO;
    subsys_sched_set_mode(&s_sched, SUBSYS_MODE_RUN);
    dzframe_parser_init(&s_rx);
    dzctl_wd_init(&s_wd, 1000u);   /* 侧车每 250 ms 发一次心跳 */
    if ((e = car_aux_init()) != DZ_OK) return e;
    return pal_timer_start(RES_TIMER_CTRL, CTRL_PERIOD_US, ctrl_isr, 0);
}

static void send(const dzframe_t *f)
{
    uint8_t out[DZFRAME_MAX_FRAME];
    size_t n = dzframe_encode(out, sizeof out, f);
    if (n) (void)link_write(out, (uint16_t)n);   /* EBUSY 时丢这一帧，下一帧补上 */
}

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
            s_state.cmd_v_mps = s_state.cmd_w_rps = 0.0f;
        } else if (dzctl_handle(&t, &f, &ack)) {
            apply_params();
            send(&ack);
        } else if (f.kind == DZF_DATA && f.id == DZCTL_ID_CMD && f.len >= 1u && f.payload[0] == 'R') {
            s_estop = false;
        } else if (!s_estop && f.kind == DZF_DATA && f.id == ID_CMD && f.len == 8u) {
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
    handle_rx(now);
    if (dzctl_wd_expired(&s_wd, now)) { s_estop = true; s_state.cmd_v_mps = s_state.cmd_w_rps = 0.0f; }
    if (car_aux_poll(now)) { s_estop = true; s_state.cmd_v_mps = s_state.cmd_w_rps = 0.0f; }   /* 只置不清 */
    s_state.cmd_v_mps = car_aux_limit_v(s_state.cmd_v_mps);
    subsys_sched_poll(&s_sched, now);
    uint32_t st = pal_irq_save();
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
    if (now - last_hb >= 500u) {
        dzctl_table_t t = link_param_table(&g_link_params);
        dzframe_t f;
        last_hb = now;
        dzctl_heartbeat(&t, seq++, &f);
        send(&f);
    }
#ifdef RES_GPIO_LED
    if (now - last_led >= 250u) { last_led = now; pal_gpio_toggle(RES_GPIO_LED); }
#else
    (void)last_led;
#endif
}
