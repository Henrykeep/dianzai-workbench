/* 仅 host-sim：绑定两路仿真电机；模拟 MaixCAM2 每 40 ms 用 dzframe 发一帧（钢珠在 −60 px 静止）。
 * 摆杆/钢珠的物理没有仿真：QD4310 下行帧只在测试里检查。 */
#include "board_gen.h"
#include "host_sim.h"
#include "dzframe.h"
#include "cp_vision_cpu.h"
#include "pal.h"

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

void host_sim_app_setup(void)
{
    host_sim_motor_t a = { RES_PWM_MOTOR_A, RES_GPIO_MOTOR_A_IN1, RES_GPIO_MOTOR_A_IN2, RES_ENCODER_MOTOR_A,
                           5.0f, 0.08f, 1456.0f, 0.3f, false };
    host_sim_motor_t b = { RES_PWM_MOTOR_B, RES_GPIO_MOTOR_B_IN1, RES_GPIO_MOTOR_B_IN2, RES_ENCODER_MOTOR_B,
                           5.0f, 0.08f, 1456.0f, 0.3f, false };
    host_sim_bind_motor(&a);
    host_sim_bind_motor(&b);
    host_sim_add_periodic(40000u, fake_camera, 0);
}
