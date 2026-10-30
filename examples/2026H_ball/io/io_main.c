/**
 * io 胶水层：唯一接触硬件的地方。读编码器/视觉帧/QD4310 回包 → io_in；跑协调器与子系统；
 * 把 chassis_out 写到 TB6612、把 beam_out 下发给 QD4310。只用逻辑资源名（RES_*），换板子不改这里。
 *
 *
 * 拆分（2026-10-29，行为不变）：上位机链路在 io_link.c，IMU 来源在 io_imu.c，本文件只剩电机/编码器/视觉/摆杆与主循环。
 */
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "board_gen.h"
#include "link_io.h"
#include "dz_compiler.h"
#include "app.h"
#include "project_gen.h"
#include "hooks.h"
#include "motor_dc.h"
#include "encoder.h"
#include "dzframe.h"
#include "dzctl.h"
#include "rtosmon.h"
#include "qd4310.h"
#include "cp_vision_cpu.h"   /* 由 boards/maixcam2-vision/board.yaml 自动生成 */
#include "io_parts.h"
#include "io_safety.h"

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

/* io 层节拍：app_loop 每 IO_TICK_MS 读一次输入，编码器 dt 用同一个数（改一处两边都跟） */
#define IO_TICK_MS 1u

static dz_err_t motor_enc(motor_dc_t *m, pal_id_t pwm, pal_id_t in1, pal_id_t in2, encoder_t *e, pal_id_t enc)
{
    const params_t *p = &g_project_params[PROFILE_BASE];
    motor_dc_cfg_t mc = motor_dc_cfg_default();
    encoder_cfg_t ec = encoder_cfg_default();
    dz_err_t r;
    mc.pwm = pwm; mc.in1 = in1; mc.in2 = in2; mc.max_duty = 0.9f;
    if ((r = motor_dc_init(m, &mc)) != DZ_OK) return r;
    ec.enc = enc; ec.counts_per_rev = p->counts_per_rev;   /* 1456：来自非最终版比赛代码，未验证（10 圈标定见 docs/12） */
    ec.dt_s = (float)IO_TICK_MS * 1e-3f; ec.speed_lpf_hz = 30.0f;
    return encoder_init(e, &ec);
}

dz_err_t app_init(void)
{
    dz_err_t e;
    if ((e = motor_enc(&MA, RES_PWM_MOTOR_A, RES_GPIO_MOTOR_A_IN1, RES_GPIO_MOTOR_A_IN2, &EA, RES_ENCODER_MOTOR_A)) != DZ_OK) return e;
    if ((e = motor_enc(&MB, RES_PWM_MOTOR_B, RES_GPIO_MOTOR_B_IN1, RES_GPIO_MOTOR_B_IN2, &EB, RES_ENCODER_MOTOR_B)) != DZ_OK) return e;
    dzframe_parser_init(&VL);
    io_link_init();
    if ((e = qd4310_init(&BEAM, RES_UART_BEAM, BEAM_MOTOR_ID)) != DZ_OK) return e;
    io_imu_init();
    if ((e = subsys_sched_init(&SCHED, g_project_subsys, PROJECT_N_SUBSYS, &S, &g_project_params[0])) != DZ_OK) return e;
    if ((e = coord_init(&COORD, &SCHED, g_project_tests, PROJECT_N_TESTS, g_project_profiles, PROJECT_N_PROFILES, &g_project_hooks)) != DZ_OK) return e;
    {
        pal_reset_cause_t rc = pal_reset_cause();
        dzctl_set_reset_cause((uint32_t)rc);
        if (io_safety_init((uint32_t)rc, pal_millis())) { dzctl_estop_note(DZCTL_ES_SAFE_BOOT, pal_millis(), (float)(uint32_t)rc); coord_event(&COORD, COORD_EV_ESTOP); }   /* 看门狗/锁死复位：等人按 R */
    }
    io_link_boot();
    return DZ_OK;
}



static void read_inputs(uint32_t now)
{
    const params_t *p = &g_project_params[COORD.profile_idx];
    uint8_t buf[64]; uint16_t got = 0, i;
    if (encoder_update(&EA) == DZ_OK && encoder_update(&EB) == DZ_OK) {
        S.io_in.wheel_a_mps = encoder_speed_rps(&EA) * p->wheel_circ_m;
        S.io_in.wheel_b_mps = encoder_speed_rps(&EB) * p->wheel_circ_m;
    } else { dzctl_estop_note(DZCTL_ES_SENSOR, now, 0.0f); coord_event(&COORD, COORD_EV_FAULT); }
    if (pal_uart_read(RES_UART_VISION, buf, sizeof buf, &got) == DZ_OK) {
        dzframe_t f; cp_vision_cpu_ball_t b;
        for (i = 0; i < got; i++)
            if (dzframe_feed(&VL, buf[i], &f) && cp_vision_cpu_ball_decode(&f, &b)) {
                S.io_in.cam_x_px = b.x_px; S.io_in.cam_flags = b.flags;
                S.io_in.cam_fseq = f.seq; S.io_in.cam_ms = b.cam_ms;
                S.io_in.cam_seq++; S.io_in.cam_rx_ms = now;
            }
    }
    io_imu_read(now, p);
    (void)qd4310_poll(&BEAM);
    S.io_in.beam_online = qd4310_online(&BEAM, now, BEAM_TIMEOUT_MS);
    S.io_in.beam_fb_deg = BEAM.fb.angle_deg;
    io_link_read();
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
    if (coord_state(&COORD) == COORD_RUNNING &&
        io_safety_step(S.chassis_out.cmd_a, S.chassis_out.cmd_b, encoder_speed_rps(&EA), encoder_speed_rps(&EB), now))
        { dzctl_estop_note(DZCTL_ES_STALL, now, fmaxf(fabsf(S.chassis_out.cmd_a), fabsf(S.chassis_out.cmd_b))); coord_event(&COORD, COORD_EV_ESTOP); }   /* 堵转：已记黑匣子，走急停路径刹车 */
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
    static uint32_t last = UINT32_MAX, last_tx;   /* last_tx：LED 闪烁节拍 */
    uint32_t now = pal_millis();
    if ((uint32_t)(now - last) < IO_TICK_MS) return;
    last = now;
    read_inputs(now);
    coord_poll(&COORD, now);
    write_outputs(now);
    io_link_write(now);
    if (now - last_tx >= 50u) {
        last_tx = now;
#ifdef RES_GPIO_LED
        pal_gpio_toggle(RES_GPIO_LED);
#endif
    }
    (void)last_tx;
}
