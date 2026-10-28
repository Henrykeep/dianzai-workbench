/* 闭环仿真：PID + 电机 + 编码器在 host-sim 上收敛。检查的是"真实"转速（仿真模型内部值），不是带量化噪声的测量。 */
#include "tt.h"
#include "board_gen.h"
#include "host_sim.h"
#include "pid.h"
#include "motor_dc.h"
#include "encoder.h"

static motor_dc_t M; static encoder_t E; static pid_ctrl_t P; static pid_inc_t PI_; static pid_cascade_t C;
static float SP; static int MODE; static int MOTOR;

static void ctrl(void *ctx)
{
    (void)ctx;
    encoder_update(&E);
    float u = 0;
    if (MODE == 0) u = pid_update(&P, SP, encoder_speed_rps(&E));
    else if (MODE == 1) u = pid_inc_update(&PI_, SP, encoder_speed_rps(&E));
    else u = pid_cascade_update(&C, SP, encoder_position_rev(&E), encoder_speed_rps(&E));
    motor_dc_set(&M, u);
}

static void setup(void)
{
    host_sim_reset(); pal_init();
    host_sim_motor_t hm = { RES_PWM_MOTOR_A, RES_GPIO_MOTOR_A_IN1, RES_GPIO_MOTOR_A_IN2, RES_ENCODER_MOTOR_A,
                            5.0f, 0.08f, 1560.0f, 0.3f, false };
    MOTOR = host_sim_bind_motor(&hm);
    motor_dc_cfg_t mc = motor_dc_cfg_default();
    mc.pwm = RES_PWM_MOTOR_A; mc.in1 = RES_GPIO_MOTOR_A_IN1; mc.in2 = RES_GPIO_MOTOR_A_IN2;
    motor_dc_init(&M, &mc);
    encoder_cfg_t ec = encoder_cfg_default();
    ec.enc = RES_ENCODER_MOTOR_A; ec.counts_per_rev = 1560; ec.dt_s = 0.001f; ec.speed_lpf_hz = 50;
    encoder_init(&E, &ec);
}

static double mean_speed(unsigned ms)
{
    double s = 0;
    for (unsigned i = 0; i < ms; i++) { host_sim_run_us(1000); s += host_sim_motor_speed_rps(MOTOR); }
    return s / ms;
}

TEST(sim_positional_speed_converges_and_rejects_load)
{
    setup();
    pid_cfg_t c = pid_cfg_default(0.001f); c.kp = 0.08f; c.ki = 1.5f;
    pid_init(&P, &c); MODE = 0; SP = 2.0f;
    pal_timer_start(RES_TIMER_CTRL, 1000, ctrl, 0);
    host_sim_run_us(1500000);
    double v = mean_speed(500);
    printf("    稳态均速 %.4f rps（目标 2.0）\n", v);
    CHECK_NEAR(v, 2.0, 0.04);
    host_sim_motor_set_load(MOTOR, 1.0f);                 /* 突加负载 */
    host_sim_run_us(1500000);
    v = mean_speed(500);
    printf("    加载后均速 %.4f rps\n", v);
    CHECK_NEAR(v, 2.0, 0.04);
    SP = -1.5f;                                           /* 反向 */
    host_sim_run_us(2000000);
    CHECK_NEAR(mean_speed(500), -1.5, 0.04);
}

TEST(sim_saturation_recovers)
{
    setup();
    pid_cfg_t c = pid_cfg_default(0.001f); c.kp = 0.08f; c.ki = 1.5f;
    pid_init(&P, &c); MODE = 0; SP = 10.0f;               /* 超过电机能力：长时间饱和 */
    pal_timer_start(RES_TIMER_CTRL, 1000, ctrl, 0);
    host_sim_run_us(3000000);
    SP = 1.0f;
    host_sim_run_us(800000);                              /* 抗饱和正确时应很快回到目标附近 */
    CHECK_NEAR(mean_speed(300), 1.0, 0.05);
}

TEST(sim_incremental_converges)
{
    setup();
    pid_cfg_t c = pid_cfg_default(0.001f); c.kp = 0.08f; c.ki = 1.5f;
    pid_inc_init(&PI_, &c); MODE = 1; SP = 2.0f;
    pal_timer_start(RES_TIMER_CTRL, 1000, ctrl, 0);
    host_sim_run_us(2000000);
    CHECK_NEAR(mean_speed(500), 2.0, 0.04);
}

TEST(sim_cascade_position_converges)
{
    setup();
    pid_cfg_t in = pid_cfg_default(0.001f); in.kp = 0.08f; in.ki = 1.5f;
    pid_cfg_t out = pid_cfg_default(0.005f); out.kp = 4.0f; out.out_min = -3; out.out_max = 3;
    out.i_min = out.i_max = 0;
    CHECK(pid_cascade_init(&C, &out, &in, 5) == DZ_OK);
    MODE = 2; SP = 3.0f;                                  /* 转到 3 圈 */
    pal_timer_start(RES_TIMER_CTRL, 1000, ctrl, 0);
    host_sim_run_us(4000000);
    printf("    位置 %.4f 圈（目标 3）\n", encoder_position_rev(&E));
    CHECK_NEAR(encoder_position_rev(&E), 3.0, 0.02);
    CHECK_NEAR(host_sim_motor_speed_rps(MOTOR), 0.0, 0.1);
}

void suite_sim(void)
{
    RUN(sim_positional_speed_converges_and_rejects_load); RUN(sim_saturation_recovers);
    RUN(sim_incremental_converges); RUN(sim_cascade_position_converges);
}
