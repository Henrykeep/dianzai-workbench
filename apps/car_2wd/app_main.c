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
 *   板 -> 上位机  HEARTBEAT  每 500 ms
 */
#include "board_gen.h"
#include "app.h"
#include "pid.h"
#include "motor_dc.h"
#include "encoder.h"
#include "dzframe.h"
#include "subsys.h"
#include "drive_plan.h"

/* ---- 机械参数：换电机/轮子改这里 ---- */
#define CTRL_PERIOD_US   1000u
#define COUNTS_PER_REV   1560.0f   /* 【未验证】轮子转一圈的累计计数（PAL 的硬件正交/软件解码均为 4 倍频）。
                                        * 两车同款电机，旧代码约 3.7 倍的 ticks/m 差异疑为倍频/单位换算错误；
                                        * 按 docs/12-参考工程与参数来源.md 的“转 10 圈”标定后填写。 */
#define ID_CMD   1u
#define ID_TELEM 2u

typedef struct { motor_dc_t motor; encoder_t enc; pid_ctrl_t pid; } wheel_t;

static wheel_t s_w[2];
static car_state_t s_state;
static subsys_sched_t s_sched;
static dzframe_parser_t s_rx;
static volatile float s_sp[2];
static volatile uint32_t s_ctrl_errors;
static const drive_params_t k_params = {
    .wheel_diam_m = 0.065f, .track_m = 0.15f, .max_rps = 5.0f, .accel_rps2 = 10.0f, .cmd_timeout_ms = 200u,
};

static void ctrl_isr(void *ctx)
{
    (void)ctx;
    for (unsigned i = 0; i < 2; i++) {
        wheel_t *w = &s_w[i];
        if (encoder_update(&w->enc) != DZ_OK) { s_ctrl_errors++; motor_dc_stop(&w->motor, MOTOR_DC_COAST); continue; }
        if (motor_dc_set(&w->motor, pid_update(&w->pid, s_sp[i], encoder_speed_rps(&w->enc))) != DZ_OK) s_ctrl_errors++;
    }
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
    pc.kp = 0.08f; pc.ki = 1.5f; pc.kd = 0.0f;   /* 起步参数，未实测，需上板整定 */
    pc.out_min = -1.0f; pc.out_max = 1.0f;
    pc.i_min = -1.0f; pc.i_max = 1.0f;
    pc.out_rate_max = 20.0f;
    return pid_init(&w->pid, &pc);
}

dz_err_t app_init(void)
{
    static const subsys_t *const list[] = { &g_drive_plan };
    dz_err_t e;
    if ((e = wheel_init(&s_w[0], RES_PWM_MOTOR_A, RES_GPIO_MOTOR_A_IN1, RES_GPIO_MOTOR_A_IN2, RES_ENCODER_MOTOR_A)) != DZ_OK) return e;
    if ((e = wheel_init(&s_w[1], RES_PWM_MOTOR_B, RES_GPIO_MOTOR_B_IN1, RES_GPIO_MOTOR_B_IN2, RES_ENCODER_MOTOR_B)) != DZ_OK) return e;
    if ((e = subsys_sched_init(&s_sched, list, 1, &s_state, &k_params)) != DZ_OK) return e;
    if (subsys_sched_selftest(&s_sched) >= 0) return DZ_EIO;
    subsys_sched_set_mode(&s_sched, SUBSYS_MODE_RUN);
    dzframe_parser_init(&s_rx);
    return pal_timer_start(RES_TIMER_CTRL, CTRL_PERIOD_US, ctrl_isr, 0);
}

static void send(const dzframe_t *f)
{
    uint8_t out[DZFRAME_MAX_FRAME];
    size_t n = dzframe_encode(out, sizeof out, f);
    if (n) (void)pal_uart_write(RES_UART_LINK, out, (uint16_t)n);   /* EBUSY 时丢这一帧，下一帧补上 */
}

static void handle_rx(uint32_t now)
{
    uint8_t buf[32]; uint16_t got = 0;
    if (pal_uart_read(RES_UART_LINK, buf, sizeof buf, &got) != DZ_OK) return;
    dzframe_t f;
    for (uint16_t i = 0; i < got; i++) {
        if (dzframe_feed(&s_rx, buf[i], &f) && f.kind == DZF_DATA && f.id == ID_CMD && f.len == 8u) {
            s_state.cmd_v_mps = dzframe_get_f32(&f, 0);
            s_state.cmd_w_rps = dzframe_get_f32(&f, 4);
            s_state.cmd_ms = now;
        }
    }
}

void app_loop(void)
{
    static uint32_t last_tx, last_hb, last_led;
    static uint8_t seq;
    uint32_t now = pal_millis();
    handle_rx(now);
    subsys_sched_poll(&s_sched, now);
    uint32_t st = pal_irq_save();
    s_sp[0] = s_state.sp_a_rps; s_sp[1] = s_state.sp_b_rps;
    pal_irq_restore(st);

    if (now - last_tx >= 20u) {
        last_tx = now;
        dzframe_t f = { .kind = DZF_DATA, .id = ID_TELEM, .seq = seq++ };
        st = pal_irq_save();
        float spd_a = encoder_speed_rps(&s_w[0].enc), spd_b = encoder_speed_rps(&s_w[1].enc);
        uint32_t err = s_ctrl_errors;
        pal_irq_restore(st);
        (void)(dzframe_put_u32(&f, now) && dzframe_put_f32(&f, s_sp[0]) && dzframe_put_f32(&f, spd_a)
               && dzframe_put_f32(&f, s_sp[1]) && dzframe_put_f32(&f, spd_b) && dzframe_put_u32(&f, err));
        send(&f);
    }
    if (now - last_hb >= 500u) {
        last_hb = now;
        dzframe_t f = { .kind = DZF_HEARTBEAT, .id = 0, .seq = seq++ };
        send(&f);
    }
#ifdef RES_GPIO_LED
    if (now - last_led >= 250u) { last_led = now; pal_gpio_toggle(RES_GPIO_LED); }
#else
    (void)last_led;
#endif
}
