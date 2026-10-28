/* 仅 host-sim：绑定两路仿真电机；模拟 MaixCAM2 每 40 ms 用 dzframe 发一帧；
 * 假 QD4310 + 钢珠物理（工作台阶跃实验 / Agent 评测用，数值是“像样”而不是实测）：
 *   QD4310：解析下行 ANGLE 帧，摆杆角一阶跟随（τ 30 ms），每 5 ms 回一帧上行反馈（CRC 用驱动同一实现）。
 *   钢珠：实心球滚动 x'' = 5/7·g·sin(θ−零点) − c·x'，杆长 ±0.25 m 硬端；相机 1 m ↔ 600 px，x 初值 −0.1 m。
 *   θ>0 让球向 +x 滚，对应 beam_dir=+1（实物方向见 QUESTIONS 10，未验证）。 */
#include "board_gen.h"
#include "host_sim.h"
#include "dzframe.h"
#include "cp_vision_cpu.h"
#include "pal.h"
#include "dzimu.h"
#include <math.h>
#include <string.h>
#include "project_gen.h"
#include "qd4310.h"

#define SIM_PX_PER_M 600.0f
static float s_beam_deg = -1.0f, s_beam_tgt = -1.0f;   /* <0：还没初始化（取零点） */
static float s_x = -0.1f, s_v;

static void fake_beam(void *ctx)     /* 1 kHz */
{
    static uint8_t rx[64]; static uint16_t n; static int k;
    const float dt = 0.001f, zero = g_project_params[0].beam_zero_deg;
    uint16_t got, i;
    (void)ctx;
    if (s_beam_deg < 0.0f) s_beam_deg = s_beam_tgt = zero;
    got = host_sim_uart_take_tx(RES_UART_BEAM, rx + n, (uint16_t)(sizeof rx - n));
    n = (uint16_t)(n + got);
    for (i = 0; (uint16_t)(n - i) >= QD4310_TX_LEN;) {            /* 找 [id][cmd][lo][hi][crc] */
        const uint8_t *f = rx + i;
        if (qd4310_crc8(f, 4u) != f[4]) { i++; continue; }
        if (f[1] == QD_CMD_ANGLE) s_beam_tgt = (float)(f[2] | (f[3] << 8)) * (360.0f / 65536.0f);
        i = (uint16_t)(i + QD4310_TX_LEN);
    }
    memmove(rx, rx + i, (size_t)(n - i)); n = (uint16_t)(n - i);
    s_beam_deg += (s_beam_tgt - s_beam_deg) * dt / 0.03f;
    s_v += (5.0f / 7.0f * 9.80665f * sinf((s_beam_deg - zero) * 0.0174533f) - 0.4f * s_v) * dt;
    s_x += s_v * dt;
    if (s_x > 0.25f) { s_x = 0.25f; s_v = 0.0f; }
    if (s_x < -0.25f) { s_x = -0.25f; s_v = 0.0f; }
    if (++k % 5 == 0) {                               /* 上行 10 字节反馈 */
        uint8_t o[QD4310_RX_LEN] = { 0 };
        uint16_t a = (uint16_t)lrintf(fmodf(s_beam_deg, 360.0f) * (65536.0f / 360.0f));
        o[0] = 0u; o[7] = (uint8_t)a; o[8] = (uint8_t)(a >> 8);
        o[9] = qd4310_crc8(o, 9u);
        host_sim_uart_inject_rx(RES_UART_BEAM, o, sizeof o);
    }
}

static void fake_camera(void *ctx)
{
    static uint8_t seq;
    cp_vision_cpu_ball_t b;
    dzframe_t f; uint8_t raw[DZFRAME_MAX_FRAME];
    size_t n;
    (void)ctx;
    b.flags = 0x09u; b.x_px = (int16_t)lrintf(s_x * SIM_PX_PER_M); b.cam_ms = pal_millis();
    if (!cp_vision_cpu_ball_encode(&b, seq++, &f)) return;
    n = dzframe_encode(raw, sizeof raw, &f);
    host_sim_uart_inject_rx(RES_UART_VISION, raw, (uint16_t)n);
}

/* 仿真 IMU 姿态模块：200 Hz 发 dzimu，前向加速度 = 两轮平均速度的差分（模块 +x 朝车头，即 imu_axis=0）。
 * 模块装歪 3°（俯仰）：原始 acc_x 带 −g·sin3° ≈ −0.51 m/s² 的重力分量，用来验证主控侧去重力。 */
#define SIM_IMU_PITCH_DEG 3.0f
static int s_ma = -1, s_mb = -1;
static void fake_imu(void *ctx)
{
    static uint8_t seq;
    static float last_v;
    static int have;
    (void)ctx;
    float v = 0.5f * (host_sim_motor_speed_rps(s_ma) + host_sim_motor_speed_rps(s_mb)) * 0.204f;
    float ax = have ? (v - last_v) / 0.005f : 0.0f;
    last_v = v; have = 1;
    const float pr = SIM_IMU_PITCH_DEG * 0.017453293f;
    dzimu_sample_t s = { pal_millis(), { ax - DZIMU_G * sinf(pr), 0.0f, DZIMU_G * cosf(pr) }, { 0.0f, 0.0f, 0.0f }, 0.0f, SIM_IMU_PITCH_DEG,
                         DZIMU_ST_ACC_OK | DZIMU_ST_GYR_OK | DZIMU_ST_ATT_OK | DZIMU_ST_BIAS_OK };
    dzframe_t f; uint8_t raw[DZFRAME_MAX_FRAME];
    if (!dzimu_encode(&s, seq++, &f)) return;
    size_t n = dzframe_encode(raw, sizeof raw, &f);
    host_sim_uart_inject_rx(RES_UART_IMU, raw, (uint16_t)n);
}

void host_sim_app_setup(void)
{
    host_sim_motor_t a = { RES_PWM_MOTOR_A, RES_GPIO_MOTOR_A_IN1, RES_GPIO_MOTOR_A_IN2, RES_ENCODER_MOTOR_A,
                           5.0f, 0.08f, 1456.0f, 0.3f, false };
    host_sim_motor_t b = { RES_PWM_MOTOR_B, RES_GPIO_MOTOR_B_IN1, RES_GPIO_MOTOR_B_IN2, RES_ENCODER_MOTOR_B,
                           5.0f, 0.08f, 1456.0f, 0.3f, false };
    s_ma = host_sim_bind_motor(&a);
    s_mb = host_sim_bind_motor(&b);
    host_sim_add_periodic(40000u, fake_camera, 0);
    host_sim_add_periodic(1000u, fake_beam, 0);
#ifdef RES_UART_IMU
    host_sim_add_periodic(5000u, fake_imu, 0);
#endif
}
