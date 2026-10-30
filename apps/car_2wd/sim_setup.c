/* 仅在 BOARD=host-sim 时编译：把两个仿真电机"接"到与真板相同的逻辑资源上。 */
#include "board_gen.h"
#include "host_sim.h"
#include "pal.h"

static uint32_t s_key_until;
static int s_key_on;
void car_sim_key(uint8_t n);
void car_sim_key(uint8_t n) { s_key_until = pal_millis() + (uint32_t)n * 100u; s_key_on = 1; host_sim_gpio_set_input(RES_GPIO_KEY, true); }
static void key_tick(void *ctx)
{
    (void)ctx;
    if (s_key_on && (int32_t)(pal_millis() - s_key_until) >= 0) { s_key_on = 0; host_sim_gpio_set_input(RES_GPIO_KEY, false); }
}

void host_sim_app_setup(void)
{
    host_sim_motor_t a = {
        .pwm = RES_PWM_MOTOR_A, .in1 = RES_GPIO_MOTOR_A_IN1, .in2 = RES_GPIO_MOTOR_A_IN2,
        .enc = RES_ENCODER_MOTOR_A, .gain_rps = 5.0f, .tau_s = 0.08f,
        .counts_per_rev = 1560.0f, .load_rps = 0.3f, .dir_mode = false,
    };
    host_sim_motor_t b = a;
    b.pwm = RES_PWM_MOTOR_B; b.in1 = RES_GPIO_MOTOR_B_IN1; b.in2 = RES_GPIO_MOTOR_B_IN2; b.enc = RES_ENCODER_MOTOR_B;
    host_sim_bind_motor(&a);
    host_sim_bind_motor(&b);
    host_sim_add_periodic(1000u, key_tick, 0);
}
