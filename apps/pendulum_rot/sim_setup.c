/* 仅 host-sim：旋转倒立摆近似模型（数值“像样”而非实测）。
 *   摆臂：ω' = (G·u − ω)/τ，G = 20 rad/s，τ = 50 ms（电机一阶）
 *   摆杆（均匀细杆 l = 0.15 m，臂长 r = 0.1 m）：α'' = 3g/(2l)·sinα − 3r/(2l)·θ''·cosα − c·α'
 *   α = 0 为竖直向上；|α| > 90° 后摆杆搁在限位上（不模拟下垂摆动）。
 *   'U' 命令把摆扶正到 +2°（模拟人手扶起），'K' n 给摆杆一下 n×0.1 rad/s 的扰动。 */
#include "board_gen.h"
#include "host_sim.h"
#include <math.h>

static float th, w, al = 0.035f, ald;   /* 上电时摆杆偏 2°，控制器立即投入 */
static double acc_a, acc_p;

static float duty_u(void)
{
    float d = (float)host_sim_pwm_duty(RES_PWM_MOTOR_A) / (float)PAL_DUTY_MAX;
    bool a = host_sim_gpio_level(RES_GPIO_MOTOR_A_IN1), b = host_sim_gpio_level(RES_GPIO_MOTOR_A_IN2);
    return a && !b ? d : (!a && b ? -d : 0.0f);
}

static void plant(void *ctx)    /* 1 kHz */
{
    const float dt = 0.001f;
    (void)ctx;
    float wd = (20.0f * duty_u() - w) / 0.05f;
    float add = 98.1f * sinf(al) - 1.0f * wd * cosf(al) - 0.5f * ald;
    w += wd * dt; th += w * dt;
    ald += add * dt; al += ald * dt;
    if (al > 1.5708f) { al = 1.5708f; ald = 0; }
    if (al < -1.5708f) { al = -1.5708f; ald = 0; }
    double ca = (double)th * (1560.0 / 6.2831853), cp = (double)al * (2400.0 / 6.2831853);
    int32_t da = (int32_t)lrint(ca - acc_a), dp = (int32_t)lrint(cp - acc_p);
    acc_a += da; acc_p += dp;
    if (da) host_sim_enc_add(RES_ENCODER_MOTOR_A, da);
    if (dp) host_sim_enc_add(RES_ENCODER_MOTOR_B, dp);
}

void link_app_sim_cmd(uint8_t c, uint8_t n);
void link_app_sim_cmd(uint8_t c, uint8_t n)
{
    if (c == 'U') { al = 0.035f; ald = 0; }
    if (c == 'K') ald += (float)(n ? n : 5) * 0.1f;
}

void host_sim_app_setup(void) { host_sim_add_periodic(1000u, plant, 0); }
