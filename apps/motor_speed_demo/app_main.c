/**
 * @file app_main.c
 * @brief 单电机速度闭环演示。
 *
 * 本文件只用逻辑资源名（RES_*），不出现任何引脚号、芯片型号或 HAL 函数。
 * 换板子 = 换 BOARD=xxx 重新编译；本文件一行不改。
 *
 *  - CTRL 定时器 1 kHz：读编码器 -> 速度 PID -> 电机
 *  - 主循环：LED 2 Hz 闪烁（活着的心跳）；每 20 ms 通过 LINK 发一行遥测；
 *            从 LINK 接收 "S<转速>\n" 修改目标转速（单位：转/秒），例如 "S2.5\n"
 */
#include <stdio.h>
#include <stdlib.h>
#include "board_gen.h"
#include "link_io.h"
#include "app.h"
#include "pid.h"
#include "motor_dc.h"
#include "encoder.h"

/* ---- 与机械相关的参数：换电机时改这里（或将来搬到 app.yaml） ---- */
#define CTRL_PERIOD_US   1000u
#define COUNTS_PER_REV   1560.0f   /* TODO(用户)：按实际电机填写 = 编码器线数 × 4 × 减速比 */
#define DEFAULT_SP_RPS   2.0f

static motor_dc_t   s_motor;
static encoder_t    s_enc;
static pid_ctrl_t   s_pid;
static volatile float s_sp = DEFAULT_SP_RPS;
static volatile uint32_t s_ctrl_ticks, s_ctrl_errors;

static void ctrl_isr(void *ctx)
{
    (void)ctx;
    if (encoder_update(&s_enc) != DZ_OK) { s_ctrl_errors++; motor_dc_stop(&s_motor, MOTOR_DC_COAST); return; }
    float u = pid_update(&s_pid, s_sp, encoder_speed_rps(&s_enc));
    if (motor_dc_set(&s_motor, u) != DZ_OK) s_ctrl_errors++;
    s_ctrl_ticks++;
}

dz_err_t app_init(void)
{
    dz_err_t e;
    motor_dc_cfg_t mc = motor_dc_cfg_default();
    mc.mode = MOTOR_DC_PWM_IN1_IN2;
    mc.pwm = RES_PWM_MOTOR_A; mc.in1 = RES_GPIO_MOTOR_A_IN1; mc.in2 = RES_GPIO_MOTOR_A_IN2;
    mc.max_duty = 0.9f;
    if ((e = motor_dc_init(&s_motor, &mc)) != DZ_OK) return e;

    encoder_cfg_t ec = encoder_cfg_default();
    ec.enc = RES_ENCODER_MOTOR_A;
    ec.counts_per_rev = COUNTS_PER_REV;
    ec.dt_s = CTRL_PERIOD_US * 1e-6f;
    ec.speed_lpf_hz = 50.0f;
    if ((e = encoder_init(&s_enc, &ec)) != DZ_OK) return e;

    pid_cfg_t pc = pid_cfg_default(CTRL_PERIOD_US * 1e-6f);
    pc.kp = 0.08f; pc.ki = 1.5f; pc.kd = 0.0f;
    pc.out_min = -1.0f; pc.out_max = 1.0f;
    pc.i_min = -1.0f; pc.i_max = 1.0f;
    pc.out_rate_max = 20.0f;               /* 满量程最快 50 ms，保护电源与齿轮 */
    if ((e = pid_init(&s_pid, &pc)) != DZ_OK) return e;

    return pal_timer_start(RES_TIMER_CTRL, CTRL_PERIOD_US, ctrl_isr, 0);
}

static void handle_rx(void)
{
    static char line[32];
    static unsigned n;
    uint8_t buf[32]; uint16_t got = 0;
    if (link_read(buf, sizeof buf, &got) != DZ_OK) return;
    for (uint16_t i = 0; i < got; i++) {
        char c = (char)buf[i];
        if (c == '\n' || c == '\r') {
            line[n] = 0;
            if (n > 1 && line[0] == 'S') {
                char *end; float v = strtof(line + 1, &end);
                if (end != line + 1 && v > -20.0f && v < 20.0f) {
                    uint32_t st = pal_irq_save(); s_sp = v; pal_irq_restore(st);
                }
            }
            n = 0;
        } else if (n < sizeof line - 1) line[n++] = c;
        else n = 0;                        /* 超长行丢弃，防止缓冲溢出 */
    }
}

void app_loop(void)
{
    static uint32_t last_led, last_tx;
    uint32_t now = pal_millis();
    if (now - last_led >= 250u) { last_led = now; pal_gpio_toggle(RES_GPIO_LED); }
    if (now - last_tx >= 20u) {
        last_tx = now;
        char msg[96];
        uint32_t st = pal_irq_save();
        float sp = s_sp, spd = encoder_speed_rps(&s_enc), out = pid_output(&s_pid);
        uint32_t err = s_ctrl_errors;
        pal_irq_restore(st);
        /* 不用 %f：newlib-nano 默认不带浮点 printf，改用整数毫单位 */
        int len = snprintf(msg, sizeof msg, "t=%lu sp=%ld spd=%ld out=%ld err=%lu\n",
                           (unsigned long)now, (long)(sp * 1000), (long)(spd * 1000),
                           (long)(out * 1000), (unsigned long)err);
        if (len > 0) (void)link_write((const uint8_t *)msg, (uint16_t)len);  /* EBUSY 时丢这一帧 */
    }
    handle_rx();
}
