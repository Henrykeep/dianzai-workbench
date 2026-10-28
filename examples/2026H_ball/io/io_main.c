/**
 * io 胶水层：唯一接触硬件的地方。读传感器 -> 写 io_in 段；运行协调器与子系统；把子系统输出写到执行器。
 * 只用逻辑资源名（RES_*），换板子不改这里。
 *
 * LINK 串口命令（每行一条）：T<n> 选测试项（下标从 0 开始）  P<n> 选参数档  G 开始  S 停止  E 急停  R 复位
 */
#include <stdio.h>
#include "board_gen.h"
#include "app.h"
#include "project_gen.h"
#include "hooks.h"
#include "motor_dc.h"
#include "encoder.h"
#include "dzframe.h"
#include "cp_vision_cpu.h"   /* 由 boards/jetson-nano-vision/board.yaml 自动生成 */

static shared_state_t S;
static subsys_sched_t SCHED;
static coord_t COORD;
static motor_dc_t MOTOR;
static encoder_t ENC;
static dzframe_parser_t VL;

shared_state_t *io_state(void) { return &S; }
coord_t *io_coord(void) { return &COORD; }

dz_err_t app_init(void)
{
    dz_err_t e;
    motor_dc_cfg_t mc = motor_dc_cfg_default();
    mc.pwm = RES_PWM_MOTOR_A; mc.in1 = RES_GPIO_MOTOR_A_IN1; mc.in2 = RES_GPIO_MOTOR_A_IN2; mc.max_duty = 0.9f;
    if ((e = motor_dc_init(&MOTOR, &mc)) != DZ_OK) return e;
    encoder_cfg_t ec = encoder_cfg_default();
    ec.enc = RES_ENCODER_MOTOR_A; ec.counts_per_rev = 1560.0f;   /* TODO(用户)：实际电机参数 */
    ec.dt_s = 0.001f; ec.speed_lpf_hz = 50.0f;
    if ((e = encoder_init(&ENC, &ec)) != DZ_OK) return e;
    dzframe_parser_init(&VL);
    if ((e = subsys_sched_init(&SCHED, g_project_subsys, PROJECT_N_SUBSYS, &S, &g_project_params[0])) != DZ_OK) return e;
    return coord_init(&COORD, &SCHED, g_project_tests, PROJECT_N_TESTS, g_project_profiles, PROJECT_N_PROFILES, &g_project_hooks);
}

static void handle_cmd(const char *l)
{
    int n = (l[1] >= '0' && l[1] <= '9') ? l[1] - '0' : -1;
    switch (l[0]) {
    case 'T': if (n >= 0) coord_select_test(&COORD, (uint8_t)n); break;
    case 'P': if (n >= 0) coord_select_profile(&COORD, (uint8_t)n); break;
    case 'G': coord_event(&COORD, COORD_EV_START); break;
    case 'S': coord_event(&COORD, COORD_EV_STOP); break;
    case 'E': coord_event(&COORD, COORD_EV_ESTOP); break;
    case 'R': coord_event(&COORD, COORD_EV_RESET); break;
    default: break;
    }
}

static void read_inputs(uint32_t now)
{
    if (encoder_update(&ENC) == DZ_OK) S.io_in.wheel_rps = encoder_speed_rps(&ENC);
    else coord_event(&COORD, COORD_EV_FAULT);
    uint8_t buf[64]; uint16_t got = 0;
    if (pal_uart_read(RES_UART_VISION, buf, sizeof buf, &got) == DZ_OK) {
        dzframe_t f; cp_vision_cpu_ball_t b;
        for (uint16_t i = 0; i < got; i++)
            if (dzframe_feed(&VL, buf[i], &f) && cp_vision_cpu_ball_decode(&f, &b)) {
                S.io_in.cam_x_px = b.x_px; S.io_in.cam_y_px = b.y_px; S.io_in.cam_found = b.found != 0;
                S.io_in.cam_seq++; S.io_in.cam_rx_ms = now;
            }
    }
    static char line[16]; static unsigned n;
    if (pal_uart_read(RES_UART_LINK, buf, sizeof buf, &got) == DZ_OK)
        for (uint16_t i = 0; i < got; i++) {
            char c = (char)buf[i];
            if (c == '\n' || c == '\r') { line[n] = 0; if (n) handle_cmd(line); n = 0; }
            else if (n < sizeof line - 1) line[n++] = c; else n = 0;
        }
}

static void write_outputs(void)
{
    if (coord_state(&COORD) == COORD_RUNNING) motor_dc_set(&MOTOR, S.chassis_out.motor_cmd);
    else motor_dc_stop(&MOTOR, coord_state(&COORD) == COORD_ESTOP ? MOTOR_DC_BRAKE : MOTOR_DC_COAST);
    pal_pwm_set_pulse_us(RES_PWM_SERVO_X, S.ball_out.servo_x_us);
    pal_pwm_set_pulse_us(RES_PWM_SERVO_Y, S.ball_out.servo_y_us);
}

/* 协作式调度：每毫秒走一轮。若主循环被阻塞超过 1 ms，调度器会记 overrun（遥测可见）。
 * 对时序要求严格的环（例如电流环）应放到 CTRL 定时器中断里，见 docs/07-应用框架.md。 */
void app_loop(void)
{
    static uint32_t last = UINT32_MAX, last_tx;
    uint32_t now = pal_millis();
    if (now == last) return;
    last = now;
    read_inputs(now);
    coord_poll(&COORD, now);
    write_outputs();
    if (now - last_tx >= 50u) {
        last_tx = now;
        char m[112];
        int len = snprintf(m, sizeof m, "t=%lu st=%s test=%u vis=%d x=%ld y=%ld sx=%u sy=%u w=%ld\n",
            (unsigned long)now, coord_state_name(coord_state(&COORD)), S.coord.test_id, S.vision_out.valid,
            (long)(S.vision_out.x_mm * 10), (long)(S.vision_out.y_mm * 10), S.ball_out.servo_x_us, S.ball_out.servo_y_us,
            (long)(S.io_in.wheel_rps * 1000));
        if (len > 0) pal_uart_write(RES_UART_LINK, (const uint8_t *)m, (uint16_t)len);
        pal_gpio_toggle(RES_GPIO_LED);
    }
}
