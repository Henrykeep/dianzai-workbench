/* 仅 host-sim：一阶直流电机模型（host_sim 内置），带恒定负载 = 静摩擦近似。数值“像样”而非实测。 */
#include "board_gen.h"
#include "host_sim.h"

void host_sim_app_setup(void)
{
    host_sim_motor_t m = { RES_PWM_MOTOR_A, RES_GPIO_MOTOR_A_IN1, RES_GPIO_MOTOR_A_IN2, RES_ENCODER_MOTOR_A,
                           5.0f, 0.06f, 1560.0f, 0.15f, false };
    host_sim_bind_motor(&m);
}
