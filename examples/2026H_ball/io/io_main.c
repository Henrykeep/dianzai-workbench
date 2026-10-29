/**
 * io 胶水层：唯一接触硬件的地方。读编码器/视觉帧/QD4310 回包 → io_in；跑协调器与子系统；
 * 把 chassis_out 写到 TB6612、把 beam_out 下发给 QD4310。只用逻辑资源名（RES_*），换板子不改这里。
 *
 * LINK 串口（可选，板上有 LINK 才编译）：dzframe/1 + dzctl（见 firmware/proto/dzctl），桌面工作台 app/ 直接连。
 *   板→PC：遥测 DATA id=2 每 20 ms（字段见 project.yaml link.telemetry），心跳带 schema 哈希，PARAM_ACK
 *   PC→板：PARAM_SET 读写“当前参数档”（板端限幅）；DATA 0x7F 急停；DATA 0x7E u8 命令：
 *          'T'+n 选测试项（n 在第 2 字节）  'P'+n 选参数档  'G' 开始  'S' 停止  'R' 复位
 *          DATA id=1 <f32 px>：上位机给钢珠目标位置（覆盖 hooks 里的默认 0；钳到 ±400 px，非有限值忽略，急停清零）。
 *          工作台的阶跃实验 / Agent 评测用它（dzbench.json step_test）。
 *
 * IMU（可选，编译期按板上资源选来源，填 io_in.imu_ax_mps2 / imu_rx_ms / imu_ok，给 ff_src=1 的加速度前馈用）：
 *   板上有 uart IMU → 收姿态模块的 dzimu 帧（RM C 型板跑 apps/imu_module）；
 *   否则有 i2c IMU   → 直接轮询 MPU6050（每 2 ms 一次，阻塞约 0.4 ms @400 kHz）；
 *   都没有           → imu_ok 恒 false，前馈自动回退为 0。
 *   安装方向用参数 imu_axis 选（0..5 = 模块 +x -x +y -y +z -z 指向车头）。
 *   去重力：imu_grav_comp=1（默认）时，uart 姿态模块路径用模块给的 roll/pitch 减掉重力分量（dzimu_linear_acc），
 *   姿态未收敛的帧视为不可用（imu_ok=0）；MPU6050 直连路径没有姿态解算，仍含重力（未处理，坡道上会偏）。
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
#ifdef RES_UART_LINK
#include "link_gen.h"
#endif
#include "qd4310.h"
#include "cp_vision_cpu.h"   /* 由 boards/maixcam2-vision/board.yaml 自动生成 */
#if defined(RES_UART_IMU)
#include "dzimu.h"
#define IO_IMU_UART 1
#elif defined(RES_I2C_IMU)
#include "mpu6050.h"
#define IO_IMU_MPU 1
#endif

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
static float s_host_sp_px;    /* 上位机给的钢珠目标（无 LINK 时恒 0） */
float io_host_ball_sp_px(void) { return s_host_sp_px; }
#if defined(IO_IMU_UART)
static dzframe_parser_t IL;   /* IMU 姿态模块帧 */
#elif defined(IO_IMU_MPU)
static mpu6050_t MPU;
#endif
#ifdef RES_UART_LINK
static dzctl_wd_t WD;
static dzframe_parser_t LL;   /* LINK 上位机帧 */
#define LINK_ID_BALL_SP 0x01u
#endif

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
#ifdef RES_UART_LINK
    dzframe_parser_init(&LL);
    dzctl_wd_init(&WD, 1000u);   /* 上位机心跳看门狗（侧车每 250 ms 发心跳；脱机比赛不布防） */
#endif
    if ((e = qd4310_init(&BEAM, RES_UART_BEAM, BEAM_MOTOR_ID)) != DZ_OK) return e;
#if defined(IO_IMU_UART)
    dzframe_parser_init(&IL);
#elif defined(IO_IMU_MPU)
    {   /* IMU 起不来不算致命：imu_ok 保持 false，前馈回退为 0 */
        mpu6050_cfg_t mc = mpu6050_cfg_default(RES_I2C_IMU);
        if (mpu6050_init(&MPU, &mc) == DZ_OK) (void)mpu6050_calib_gyro(&MPU, 200u, 1u);
    }
#endif
    if ((e = subsys_sched_init(&SCHED, g_project_subsys, PROJECT_N_SUBSYS, &S, &g_project_params[0])) != DZ_OK) return e;
    return coord_init(&COORD, &SCHED, g_project_tests, PROJECT_N_TESTS, g_project_profiles, PROJECT_N_PROFILES, &g_project_hooks);
}

#ifdef RES_UART_LINK
static uint8_t link_seq;

static void link_send(dzframe_t *f)
{
    uint8_t out[DZFRAME_MAX_FRAME];
    size_t n;
    f->seq = link_seq++;
    n = dzframe_encode(out, sizeof out, f);
    if (n) (void)link_write(out, (uint16_t)n);   /* EBUSY 丢帧：遥测下一拍补，ACK 由上位机超时重发 */
}

/* 仿真专用命令的钩子：真板上是空函数；host-sim 的 sim_setup.c 覆盖它（如 'V' = 让假相机停发，测 HELD/LOST） */
DZ_WEAK void io_sim_cmd(uint8_t c, uint8_t n);
DZ_WEAK void io_sim_cmd(uint8_t c, uint8_t n) { (void)c; (void)n; }

static void handle_cmd(const dzframe_t *f)
{
    uint8_t n = f->len > 1u ? f->payload[1] : 0u;
    switch (f->payload[0]) {
    case 'T': coord_select_test(&COORD, n); break;
    case 'P': coord_select_profile(&COORD, n); break;
    case 'G': coord_event(&COORD, COORD_EV_START); break;
    case 'S': coord_event(&COORD, COORD_EV_STOP); break;
    case 'R': coord_event(&COORD, COORD_EV_RESET); break;
    default: io_sim_cmd(f->payload[0], n); break;
    }
}

static void read_link(void)
{
    uint8_t buf[32]; uint16_t got = 0, i;
    dzframe_t f, ack;
    dzctl_table_t t = link_param_table(&g_project_params[COORD.profile_idx]);
    if (dzctl_wd_expired(&WD, pal_millis())) coord_event(&COORD, COORD_EV_ESTOP);   /* 急停路径负责输出归零 */
    if (link_read(buf, sizeof buf, &got) != DZ_OK) return;
    for (i = 0; i < got; i++) {
        if (!dzframe_feed(&LL, buf[i], &f)) continue;
        dzctl_wd_feed(&WD, &f, pal_millis());
        if (dzctl_is_estop(&f)) { coord_event(&COORD, COORD_EV_ESTOP); s_host_sp_px = 0.0f; }
        else if (dzctl_handle(&t, &f, &ack)) link_send(&ack);
        else if (f.kind == DZF_DATA && f.id == DZCTL_ID_CMD && f.len >= 1u) handle_cmd(&f);
        else if (f.kind == DZF_DATA && f.id == LINK_ID_BALL_SP && f.len == 4u) {
            float v; memcpy(&v, f.payload, 4u);
            if (isfinite(v)) s_host_sp_px = v > 400.0f ? 400.0f : (v < -400.0f ? -400.0f : v);
        }
    }
}

static void write_link(uint32_t now)
{
    static uint32_t last_tx;
    static uint32_t last_hb = 0u - 500u;   /* 复位后第一拍就发心跳，上位机马上认出 schema */
    dzframe_t f;
    if (now - last_tx >= LINK_TELEM_PERIOD_MS) {
        link_telem_t t;
        last_tx = now;
        t.t_ms = now; t.state = (uint8_t)coord_state(&COORD); t.test_id = S.coord.test_id;
        t.cam_x_px = S.io_in.cam_x_px; t.ball_sp_px = S.coord.ball_sp_px;
        t.angle_deg = S.beam_out.angle_deg; t.beam_fb_deg = S.io_in.beam_fb_deg;
        t.wheel_a_mps = S.io_in.wheel_a_mps; t.wheel_b_mps = S.io_in.wheel_b_mps;
        t.bb_state = S.beam_out.state; t.beam_online = S.io_in.beam_online ? 1u : 0u;
        t.vis_state = S.vision_out.state; t.vis_age_ms = S.vision_out.age_ms; t.vis_drops = S.vision_out.drops;
        t.vis_lat_ms = (int16_t)(S.vision_out.lat_jit_ms > 32767 ? 32767 : S.vision_out.lat_jit_ms);
        t.ff_deg = S.beam_out.ff_deg;
        t.imu_ax_mps2 = S.io_in.imu_ax_mps2; t.imu_ok = S.io_in.imu_ok ? 1u : 0u;
        t.cpu_pm = rtosmon_cpu_permille(&g_rtosmon); t.stk_min_w = rtosmon_stack_min_words(&g_rtosmon);   /* 裸机 = 0xFFFF */
        if (link_telem_pack(&f, &t)) link_send(&f);
    }
    if (now - last_hb >= 500u) {
        dzctl_table_t pt = link_param_table(&g_project_params[COORD.profile_idx]);
        last_hb = now;
        dzctl_heartbeat(&pt, 0, &f);
        link_send(&f);
    }
}
#endif

static void read_imu(uint32_t now, const params_t *p)
{
#if defined(IO_IMU_UART)
    uint8_t buf[64]; uint16_t got = 0, i;
    if (pal_uart_read(RES_UART_IMU, buf, sizeof buf, &got) == DZ_OK) {
        dzframe_t f; dzimu_sample_t s;
        for (i = 0; i < got; i++)
            if (dzframe_feed(&IL, buf[i], &f) && dzimu_decode(&f, &s)) {
                float lin[3];
                bool att = dzimu_linear_acc(&s, lin);
                S.io_in.imu_ok = (s.status & DZIMU_ST_ACC_OK) && !(s.status & DZIMU_ST_ACC_SAT) && (att || !p->imu_grav_comp);
                if (S.io_in.imu_ok) {
                    S.io_in.imu_ax_mps2 = dzimu_axis(p->imu_grav_comp ? lin : s.acc, p->imu_axis);
                    S.io_in.imu_rx_ms = now;
                }
            }
    }
#elif defined(IO_IMU_MPU)
    mpu6050_data_t d;
    if (!MPU.ok || now % 2u) return;
    S.io_in.imu_ok = mpu6050_read(&MPU, &d) == DZ_OK && !d.acc_sat;
    if (S.io_in.imu_ok) { S.io_in.imu_ax_mps2 = dzimu_axis(d.acc, p->imu_axis); S.io_in.imu_rx_ms = now; }
#else
    (void)now; (void)p;
    S.io_in.imu_ok = false;
#endif
}

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
                S.io_in.cam_fseq = f.seq; S.io_in.cam_ms = b.cam_ms;
                S.io_in.cam_seq++; S.io_in.cam_rx_ms = now;
            }
    }
    read_imu(now, p);
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
    static uint32_t last = UINT32_MAX, last_tx;   /* last_tx：LED 闪烁节拍 */
    uint32_t now = pal_millis();
    if (now == last) return;
    last = now;
    read_inputs(now);
    coord_poll(&COORD, now);
    write_outputs(now);
#ifdef RES_UART_LINK
    write_link(now);
#endif
    if (now - last_tx >= 50u) {
        last_tx = now;
#ifdef RES_GPIO_LED
        pal_gpio_toggle(RES_GPIO_LED);
#endif
    }
    (void)last_tx;
}
