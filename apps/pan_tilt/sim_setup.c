/* 仅 host-sim：云台 + 相机近似模型（数值“像样”而非实测）。
 *   舵机：实际角一阶跟随指令（τ 60 ms）；指令角从 PWM 脉宽反算（500–2500 us ↔ ±90°）。
 *   目标：世界坐标里的一个点，默认静止在 (+8°, −3°)；'M' n 让它画圆（n×0.1 rad/s，0 停）。
 *   相机：30 fps，曝光到出帧 50 ms 延迟，10 px/deg，视场 ±16°（出视场就发 valid=0）。
 *   'V' n：相机停发 n×0.1 s（0 = 3 s），用来看 HELD → LOST → VALID。 */
#include "board_gen.h"
#include "host_sim.h"
#include "dzframe.h"
#include <math.h>

#define LAT_STEPS 10     /* 50 ms / 5 ms */
static float pan, tilt, tx = 8.0f, ty = -3.0f, w_tgt, ph;
static float hist_x[LAT_STEPS], hist_y[LAT_STEPS];
static unsigned hi;
static uint32_t off_until;

static float servo_deg(pal_id_t id)
{
    float us = (float)host_sim_pwm_duty(id) / (float)PAL_DUTY_MAX * 20000.0f;
    return us < 400.0f ? 0.0f : (us - 1500.0f) * 0.09f;
}

static void plant(void *ctx)     /* 200 Hz */
{
    (void)ctx;
    pan += (servo_deg(RES_PWM_SERVO_X) - pan) * 0.005f / 0.06f;
    tilt += (servo_deg(RES_PWM_SERVO_Y) - tilt) * 0.005f / 0.06f;
    if (w_tgt != 0.0f) { ph += w_tgt * 0.005f; tx = 8.0f * cosf(ph); ty = 5.0f * sinf(ph); }
    hist_x[hi] = tx - pan; hist_y[hi] = ty - tilt; hi = (hi + 1u) % LAT_STEPS;
}

static void camera(void *ctx)    /* 30 fps */
{
    static uint8_t seq;
    (void)ctx;
    if ((int32_t)(off_until - pal_millis()) > 0) return;
    float ex = hist_x[hi] * 10.0f, ey = hist_y[hi] * 10.0f;          /* hi 指向最旧的一格 = 50 ms 前 */
    bool valid = fabsf(ex) < 160.0f && fabsf(ey) < 120.0f;
    dzframe_t f = { DZF_DATA, 0x30u, seq++, 0, { 0 } };
    uint8_t raw[DZFRAME_MAX_FRAME];
    dzframe_put_u8(&f, valid); dzframe_put_u16(&f, (uint16_t)(int16_t)lrintf(ex)); dzframe_put_u16(&f, (uint16_t)(int16_t)lrintf(ey));
    dzframe_put_u32(&f, pal_millis() - 50u);
    size_t n = dzframe_encode(raw, sizeof raw, &f);
    host_sim_uart_inject_rx(RES_UART_VISION, raw, (uint16_t)n);
}

void link_app_sim_cmd(uint8_t c, uint8_t n);
void link_app_sim_cmd(uint8_t c, uint8_t n)
{
    if (c == 'V') off_until = pal_millis() + (n ? (uint32_t)n * 100u : 3000u);
    if (c == 'M') w_tgt = (float)n * 0.1f;
}

void host_sim_app_setup(void)
{
    host_sim_add_periodic(5000u, plant, 0);
    host_sim_add_periodic(33333u, camera, 0);
}
