/**
 * io 胶水层：唯一接触硬件的地方。读编码器/视觉帧/QD4310 回包 → io_in；跑协调器与子系统；
 * 把 chassis_out 写到 TB6612、把 beam_out 下发给 QD4310。只用逻辑资源名（RES_*），换板子不改这里。
 *
 * LINK 串口（可选，板上有 LINK 才编译）命令每行一条：T<n> 选测试项  P<n> 选参数档  G 开始  S 停止  E 急停  R 复位
 */
#include <math.h>
#include <stdio.h>
#include "board_gen.h"
#include "app.h"
#include "project_gen.h"
#include "hooks.h"
#include "motor_dc.h"
#include "encoder.h"
#include "dzframe.h"
#include "qd4310.h"
#include "cp_vision_cpu.h"   /* 由 boards/maixcam2-vision/board.yaml 自动生成 */

#define BEAM_MOTOR_ID     0u      /* P1/P2：电机 ID 0（未验证） */
#define BEAM_TIMEOUT_MS   100u
#define BEAM_REFRESH_MS   40u     /* P1：40 ms 强制刷新一次 */
#define BEAM_QUANT_DEG    0.01f   /* P1：输出量化 0.01° */

static shared_state_t S;
static subsys_sched_t SCHED;
static coord_t COORD;
static motor_dc_t MA, MB;
static encoder_t EA, EB;
static dzframe_parser_t VL;
static qd4310_t BEAM;

shared_state_t *io_state(void) { return &S; }
coord_t *io_coord(void) { return &COORD; }

static dz_err_t motor_enc(motor_dc_t *m, pal_id_t pwm, pal_id_t in1, pal_id_t in2, encoder_t *e, pal_id_t enc)
{
    const params_t *p = &g_project_params[PROFILE_BASE];
    motor_dc_cfg_t mc = motor_dc_cfg_default();
    encoder_cfg_t ec = encoder_cfg_default();
    dz_err_t r;
    mc.pwm = pwm; mc.in1 = in1; mc.in2 = in2; mc.max_duty = 0.9f;
    if ((r = motor_dc_init(m, &mc)) != DZ_OK) return r;
    ec.enc = enc; ec.counts_per_rev = p->counts_per_rev;   /* 1456：来自非最终版比赛代码，未验证（10 圈标定见 docs/12） */
    ec.dt_s = 0.001f; ec.speed_lpf_hz = 30.0f;
    return encoder_init(e, &ec);
}

dz_err_t app_init(void)
{
    dz_err_t e;
    if ((e = motor_enc(&MA, RES_PWM_MOTOR_A, RES_GPIO_MOTOR_A_IN1, RES_GPIO_MOTOR_A_IN2, &EA, RES_ENCODER_MOTOR_A)) != DZ_OK) return e;
    if ((e = motor_enc(&MB, RES_PWM_MOTOR_B, RES_GPIO_MOTOR_B_IN1, RES_GPIO_MOTOR_B_IN2, &EB, RES_ENCODER_MOTOR_B)) != DZ_OK) return e;
    dzframe_parser_init(&VL);
    if ((e = qd4310_init(&BEAM, RES_UART_BEAM, BEAM_MOTOR_ID)) != DZ_OK) return e;
    if ((e = subsys_sched_init(&SCHED, g_project_subsys, PROJECT_N_SUBSYS, &S, &g_project_params[0])) != DZ_OK) return e;
    return coord_init(&COORD, &SCHED, g_project_tests, PROJECT_N_TESTS, g_project_profiles, PROJECT_N_PROFILES, &g_project_hooks);
}

#ifdef RES_UART_LINK
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

static void read_link(void)
{
    static char line[16]; static unsigned n;
    uint8_t buf[32]; uint16_t got = 0, i;
    if (pal_uart_read(RES_UART_LINK, buf, sizeof buf, &got) != DZ_OK) return;
    for (i = 0; i < got; i++) {
        char c = (char)buf[i];
        if (c == '\n' || c == '\r') { line[n] = 0; if (n) handle_cmd(line); n = 0; }
        else if (n < sizeof line - 1) line[n++] = c; else n = 0;
    }
}
#endif

static void read_inputs(uint32_t now)
{
    const params_t *p = &g_project_params[COORD.profile_idx];
    uint8_t buf[64]; uint16_t got = 0, i;
    if (encoder_update(&EA) == DZ_OK && encoder_update(&EB) == DZ_OK) {
        S.io_in.wheel_a_mps = encoder_speed_rps(&EA) * p->wheel_circ_m;
        S.io_in.wheel_b_mps = encoder_speed_rps(&EB) * p->wheel_circ_m;
    } else coord_event(&COORD, COORD_EV_FAULT);
    if (pal_uart_read(RES_UART_VISION, buf, sizeof buf, &got) == DZ_OK) {
        dzframe_t f; cp_vision_cpu_ball_t b;
        for (i = 0; i < got; i++)
            if (dzframe_feed(&VL, buf[i], &f) && cp_vision_cpu_ball_decode(&f, &b)) {
                S.io_in.cam_x_px = b.x_px; S.io_in.cam_flags = b.flags;
                S.io_in.cam_seq++; S.io_in.cam_rx_ms = now;
            }
    }
    (void)qd4310_poll(&BEAM);
    S.io_in.beam_online = qd4310_online(&BEAM, now, BEAM_TIMEOUT_MS);
    S.io_in.beam_fb_deg = BEAM.fb.angle_deg;
#ifdef RES_UART_LINK
    read_link();
#endif
}

/* 摆杆下发：只发不等；角度变化 ≥0.01° 或满 40 ms 才发（P1 的节流做法）。运行态外回零点，急停失能。 */
static void write_beam(uint32_t now)
{
    static int last_st = -1;                                /* -1：上电后还没使能过 */
    static float last_deg = NAN;
    static uint32_t last_ms;
    const params_t *p = &g_project_params[COORD.profile_idx];
    coord_state_t cs = coord_state(&COORD);
    float deg = (cs == COORD_RUNNING) ? S.beam_out.target_abs_deg : p->beam_zero_deg;
    if ((int)cs != last_st) {
        if (cs == COORD_ESTOP) (void)qd4310_enable(&BEAM, false);
        else if (last_st == -1 || last_st == (int)COORD_ESTOP) (void)qd4310_enable(&BEAM, true);
        last_st = (int)cs;
        last_deg = NAN;
        return;                                             /* 本拍只发使能/失能，下一拍发角度 */
    }
    if (cs == COORD_ESTOP) return;
    deg = roundf(deg / BEAM_QUANT_DEG) * BEAM_QUANT_DEG;
    if (!(fabsf(deg - last_deg) >= BEAM_QUANT_DEG * 0.5f) && (uint32_t)(now - last_ms) < BEAM_REFRESH_MS) return;
    if (qd4310_set_angle_deg(&BEAM, deg) == DZ_OK) { last_deg = deg; last_ms = now; }
}

static void write_outputs(uint32_t now)
{
    if (coord_state(&COORD) == COORD_RUNNING) {
        motor_dc_set(&MA, S.chassis_out.cmd_a);
        motor_dc_set(&MB, S.chassis_out.cmd_b);
    } else {
        motor_dc_stop_t m = coord_state(&COORD) == COORD_ESTOP ? MOTOR_DC_BRAKE : MOTOR_DC_COAST;
        motor_dc_stop(&MA, m); motor_dc_stop(&MB, m);
    }
    if (now % 10u == 0u) write_beam(now);
}

void app_loop(void)
{
    static uint32_t last = UINT32_MAX, last_tx;
    uint32_t now = pal_millis();
    if (now == last) return;
    last = now;
    read_inputs(now);
    coord_poll(&COORD, now);
    write_outputs(now);
    if (now - last_tx >= 50u) {
        last_tx = now;
#ifdef RES_UART_LINK
        {
            char m[112];
            int len = snprintf(m, sizeof m, "t=%lu st=%s test=%u x=%d bb=%u ang=%ld abs=%ld beam=%d v=%ld\n",
                (unsigned long)now, coord_state_name(coord_state(&COORD)), S.coord.test_id, S.io_in.cam_x_px,
                S.beam_out.state, (long)(S.beam_out.angle_deg * 100), (long)(S.beam_out.target_abs_deg * 100),
                S.io_in.beam_online, (long)(S.io_in.wheel_a_mps * 1000));
            if (len > 0) pal_uart_write(RES_UART_LINK, (const uint8_t *)m, (uint16_t)len);
        }
#endif
#ifdef RES_GPIO_LED
        pal_gpio_toggle(RES_GPIO_LED);
#endif
    }
}
