/* 仅 host-sim：绑定仿真电机；并模拟一个"Jetson Nano"每 33 ms 发一帧钢珠坐标（钢珠在 (360,250) 像素静止）。 */
#include "board_gen.h"
#include "host_sim.h"
#include "vision_link.h"

static void fake_camera(void *ctx)
{
    (void)ctx;
    char b[32]; vision_frame_t f = { 360, 250, true };
    int n = vision_link_format(b, sizeof b, &f);
    host_sim_uart_inject_rx(RES_UART_VISION, (const uint8_t *)b, (uint16_t)n);
}

void host_sim_app_setup(void)
{
    host_sim_motor_t m = { RES_PWM_MOTOR_A, RES_GPIO_MOTOR_A_IN1, RES_GPIO_MOTOR_A_IN2, RES_ENCODER_MOTOR_A,
                           5.0f, 0.08f, 1560.0f, 0.3f, false };
    host_sim_bind_motor(&m);
    host_sim_add_periodic(33000u, fake_camera, 0);
}
