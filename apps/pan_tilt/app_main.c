/**
 * @file app_main.c
 * @brief 视觉云台：VISION 串口收目标帧 → vis_link 判时效 → 每个新帧做一次像素误差 PI → 两路舵机。
 *
 * VISION 帧（dzframe DATA id=0x30，通用、不绑定具体相机 / 目标）：
 *   u8 valid, i16 ex_px, i16 ey_px, u32 cam_ms     ex/ey = 目标相对图像中心的像素（右 / 下为正）
 * 瞄准点 aim_x_px 由 LINK DATA id=1 给（f32 px，默认 0 = 图像中心），工作台阶跃实验改它。
 */
#include "board_gen.h"
#include "app.h"
#include "servo.h"
#include "vis.h"
#include "link_app.h"

#define CTRL_PERIOD_US 5000u
#define ID_TARGET 0x30u

static servo_t s_pan, s_tilt;
static vis_link_t s_vis;
static dzframe_parser_t s_vrx;
static link_app_t L;
static float s_pan_cmd, s_tilt_cmd, s_ix, s_iy, s_ex, s_ey;
static vis_state_t s_vs;

static void ctrl_isr(void *ctx) { (void)ctx; (void)servo_tick(&s_pan, CTRL_PERIOD_US * 1e-6f); (void)servo_tick(&s_tilt, CTRL_PERIOD_US * 1e-6f); }

static void apply_params(void)
{
    s_vis.cfg.hold_ms = g_link_params.hold_ms;
    s_vis.cfg.lost_ms = g_link_params.lost_ms > g_link_params.hold_ms ? g_link_params.lost_ms : g_link_params.hold_ms + 1u;
}

/* 新的一帧：误差换成角度，按 kp/ki 补一部分 */
static void on_target(float ex, float ey)
{
    const float k = 1.0f / g_link_params.px_per_deg;
    float ax = (ex - L.sp[0]) * k, ay = ey * k;
    s_ix += ax * g_link_params.ki; s_iy += ay * g_link_params.ki;
    s_pan_cmd += g_link_params.kp * ax + s_ix * (g_link_params.ki > 0 ? 1.0f : 0.0f);
    s_tilt_cmd += g_link_params.kp * ay + s_iy * (g_link_params.ki > 0 ? 1.0f : 0.0f);
    if (s_ix > 5) s_ix = 5;
    if (s_ix < -5) s_ix = -5;
    if (s_iy > 5) s_iy = 5;
    if (s_iy < -5) s_iy = -5;
}

static void poll_vision(uint32_t now)
{
    uint8_t buf[64]; uint16_t got = 0;
    dzframe_t f;
    if (pal_uart_read(RES_UART_VISION, buf, sizeof buf, &got) != DZ_OK) return;
    for (uint16_t i = 0; i < got; i++) {
        if (!dzframe_feed(&s_vrx, buf[i], &f) || f.kind != DZF_DATA || f.id != ID_TARGET || f.len < 9u) continue;
        bool valid = dzframe_get_u8(&f, 0) != 0u;
        float ex = (float)(int16_t)dzframe_get_u16(&f, 1), ey = (float)(int16_t)dzframe_get_u16(&f, 3);
        vis_link_feed(&s_vis, f.seq, dzframe_get_u32(&f, 5), now, valid, ex);
        if (valid) { s_ex = ex; s_ey = ey; if (!L.estop) on_target(ex, ey); }
    }
}

dz_err_t app_init(void)
{
    dz_err_t e;
    servo_cfg_t c = servo_cfg_default(RES_PWM_SERVO_X);
    c.lim_lo_deg = -80; c.lim_hi_deg = 80; c.slew_dps = 400;
    if ((e = servo_init(&s_pan, &c)) != DZ_OK) return e;
    c.pwm = RES_PWM_SERVO_Y; c.lim_lo_deg = -45; c.lim_hi_deg = 45;
    if ((e = servo_init(&s_tilt, &c)) != DZ_OK) return e;
    vis_link_cfg_t vc = { 100u, 500u, 200u };
    if ((e = vis_link_init(&s_vis, &vc)) != DZ_OK) return e;
    dzframe_parser_init(&s_vrx);
    link_app_init(&L, apply_params, 0);
    apply_params();
    return pal_timer_start(RES_TIMER_CTRL, CTRL_PERIOD_US, ctrl_isr, 0);
}

void app_loop(void)
{
    uint32_t now = pal_millis();
    poll_vision(now);
    s_vs = vis_link_poll(&s_vis, now);
    if (s_pan_cmd > 80) s_pan_cmd = 80;
    if (s_pan_cmd < -80) s_pan_cmd = -80;
    if (s_tilt_cmd > 45) s_tilt_cmd = 45;
    if (s_tilt_cmd < -45) s_tilt_cmd = -45;
    if (!L.estop) {                       /* LOST / 急停：舵机停在当前位置（不回中，免得甩） */
        uint32_t st = pal_irq_save();
        (void)servo_set_deg(&s_pan, s_pan_cmd); (void)servo_set_deg(&s_tilt, s_tilt_cmd);
        pal_irq_restore(st);
    } else { s_pan_cmd = s_pan.angle; s_tilt_cmd = s_tilt.angle; s_ix = s_iy = 0; }
    if (!link_app_poll(&L, now)) return;
    link_telem_t t = { 0 };
    uint32_t age = vis_link_age_ms(&s_vis, now);
    t.t_ms = now; t.aim_x_px = L.sp[0]; t.tgt_x_px = s_ex; t.tgt_y_px = s_ey;
    t.pan_deg = s_pan.angle; t.tilt_deg = s_tilt.angle;
    t.vis_state = (uint8_t)s_vs; t.vis_age_ms = age == UINT32_MAX ? 0u : age; t.vis_drops = s_vis.drops;
    link_app_send_telem(&L, &t);
}
