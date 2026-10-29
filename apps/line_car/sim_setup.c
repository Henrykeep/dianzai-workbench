/* 仅 host-sim：循线小车近似模型（数值“像样”而非实测）。
 *   两路仿真电机（host_sim 内置一阶模型）；轮径 65 mm、轮距 150 mm 的差速运动学。
 *   赛道：正弦线 y = 0.12·sin(2πx/2.4) m，线宽 18 mm；8 路灰度在车轴前 100 mm，间距 12 mm。
 *   'O' n：车横向挪 n mm（左正，n≤127；模拟被撞偏），用来测恢复；挪太多会丢线。 */
#include "board_gen.h"
#include "host_sim.h"
#include <math.h>

static int ma = -1, mb = -1;
static float x, y, psi;

static float line_y(float xx) { return 0.12f * sinf(6.2831853f * xx / 2.4f); }

static void plant(void *ctx)     /* 1 kHz */
{
    static const pal_id_t ids[8] = { RES_GPIO_LINE0, RES_GPIO_LINE1, RES_GPIO_LINE2, RES_GPIO_LINE3,
                                     RES_GPIO_LINE4, RES_GPIO_LINE5, RES_GPIO_LINE6, RES_GPIO_LINE7 };
    const float dt = 0.001f, r = 0.0325f, track = 0.15f;
    (void)ctx;
    float vl = host_sim_motor_speed_rps(ma) * 6.2831853f * r, vr = host_sim_motor_speed_rps(mb) * 6.2831853f * r;
    float v = 0.5f * (vl + vr);
    psi += (vr - vl) / track * dt;
    x += v * cosf(psi) * dt; y += v * sinf(psi) * dt;
    for (unsigned i = 0; i < 8; i++) {
        float s = ((float)i - 3.5f) * 0.012f;                     /* 右偏为正 */
        float px = x + 0.1f * cosf(psi) + s * sinf(psi), py = y + 0.1f * sinf(psi) - s * cosf(psi);
        host_sim_gpio_set_input(ids[i], fabsf(py - line_y(px)) < 0.009f);
    }
}

void link_app_sim_cmd(uint8_t c, uint8_t n);
void link_app_sim_cmd(uint8_t c, uint8_t n) { if (c == 'O') y += (float)(int8_t)n * 0.001f; }

void host_sim_app_setup(void)
{
    host_sim_motor_t a = { RES_PWM_MOTOR_A, RES_GPIO_MOTOR_A_IN1, RES_GPIO_MOTOR_A_IN2, RES_ENCODER_MOTOR_A, 5.0f, 0.08f, 1560.0f, 0.3f, false };
    host_sim_motor_t b = a;
    b.pwm = RES_PWM_MOTOR_B; b.in1 = RES_GPIO_MOTOR_B_IN1; b.in2 = RES_GPIO_MOTOR_B_IN2; b.enc = RES_ENCODER_MOTOR_B;
    ma = host_sim_bind_motor(&a); mb = host_sim_bind_motor(&b);
    psi = atanf(0.12f * 6.2831853f / 2.4f);                       /* 起点沿线切向 */
    host_sim_add_periodic(1000u, plant, 0);
}
