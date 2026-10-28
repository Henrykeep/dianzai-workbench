/* 仅 host-sim：绑定两路仿真电机；模拟 MaixCAM2 每 40 ms 用 dzframe 发一帧（钢珠在 −60 px 静止）。
 * 摆杆/钢珠的物理没有仿真：QD4310 下行帧只在测试里检查。 */
#include "board_gen.h"
#include "host_sim.h"
#include "dzframe.h"
#include "cp_vision_cpu.h"
#include "pal.h"
#include "dzimu.h"
#include <math.h>

static void fake_camera(void *ctx)
{
    static uint8_t seq;
    cp_vision_cpu_ball_t b;
    dzframe_t f; uint8_t raw[DZFRAME_MAX_FRAME];
    size_t n;
    (void)ctx;
    b.flags = 0x09u; b.x_px = -60; b.cam_ms = pal_millis();
    if (!cp_vision_cpu_ball_encode(&b, seq++, &f)) return;
    n = dzframe_encode(raw, sizeof raw, &f);
    host_sim_uart_inject_rx(RES_UART_VISION, raw, (uint16_t)n);
}

/* 仿真 IMU 姿态模块：200 Hz 发 dzimu，前向加速度 = 两轮平均速度的差分（模块 +x 朝车头，即 imu_axis=0） */
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
    dzimu_sample_t s = { pal_millis(), { ax, 0.0f, 9.80665f }, { 0.0f, 0.0f, 0.0f }, 0.0f, 0.0f,
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
#ifdef RES_UART_IMU
    host_sim_add_periodic(5000u, fake_imu, 0);
#endif
}
