/* 仅在 BOARD=host-sim 时编译：把仿真电机"接"到与真板相同的逻辑资源上。 */
#include "board_gen.h"
#include "host_sim.h"

void host_sim_app_setup(void)
{
    host_sim_motor_t m = {
        .pwm = RES_PWM_MOTOR_A, .in1 = RES_GPIO_MOTOR_A_IN1, .in2 = RES_GPIO_MOTOR_A_IN2,
        .enc = RES_ENCODER_MOTOR_A, .gain_rps = 5.0f, .tau_s = 0.08f,
        .counts_per_rev = 1560.0f, .load_rps = 0.3f, .dir_mode = false,
    };
    host_sim_bind_motor(&m);
}
