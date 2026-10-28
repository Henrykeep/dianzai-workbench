/* 仅 host-sim：绑定仿真电机；并模拟一个"Jetson Nano"每 33 ms 用 dzframe 发一帧钢珠坐标（钢珠在 (360,250) 像素静止）。 */
#include "board_gen.h"
#include "host_sim.h"
#include "dzframe.h"
#include "cp_vision_cpu.h"

static void fake_camera(void *ctx)
{
    (void)ctx;
    static uint8_t seq;
    cp_vision_cpu_ball_t b = { 360, 250, 1 };
    dzframe_t f; uint8_t raw[DZFRAME_MAX_FRAME];
    if (!cp_vision_cpu_ball_encode(&b, seq++, &f)) return;
    size_t n = dzframe_encode(raw, sizeof raw, &f);
    host_sim_uart_inject_rx(RES_UART_VISION, raw, (uint16_t)n);
}

void host_sim_app_setup(void)
{
    host_sim_motor_t m = { RES_PWM_MOTOR_A, RES_GPIO_MOTOR_A_IN1, RES_GPIO_MOTOR_A_IN2, RES_ENCODER_MOTOR_A,
                           5.0f, 0.08f, 1560.0f, 0.3f, false };
    host_sim_bind_motor(&m);
    host_sim_add_periodic(33000u, fake_camera, 0);
}
