/* 仅 host-sim：后车 = 本固件（真代码），前车 = 这里的虚拟车（脚本化里程，发真实 peerlink 帧）。
 *   被控对象同 apps/line_car：两轮一阶电机、轮径 65 mm、轮距 150 mm；正弦赛道 y = 0.12·sin(2πx/2.4)；8 路灰度在车头 100 mm。
 *   虚拟前车：沿同一条线跑（只算里程），按 v_base 以 1 m/s² 加速；每 20 ms 往 PEER 串口塞一帧 STATE；
 *   后车发来的 ABORT 会让前车也停（双向中止）。
 *   仿真命令（上位机 cmd）：
 *     'B' 前车 2 m/s² 急刹到停（停稳后发 STOPPED）   'G' 前车重新出发
 *     'X' 链路断（前车不再发帧）  'Y' 链路恢复       'A' 前车连发 3 帧 ABORT
 *     'O' n 后车横向挪 n mm（被撞偏，测丢线）
 *   真间距（gap0 + 前车里程 − 后车真里程）在仿真侧单独算（不信固件自己的估计）：'Q' 把区间最小值写进
 *   环境变量 DZ_SIM_TRUTH 指的文件（覆盖写一行）并清零重新统计；回归测试读它判“没撞车”。 */
#include "board_gen.h"
#include "host_sim.h"
#include "link_gen.h"
#include "peerlink.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static int ma = -1, mb = -1;
static float x, y, psi, s_true;
static float lead_s, lead_v;
static bool lead_brake, link_cut, lead_abort_rx;
static uint8_t lead_seq;
static int abort_burst;
static float gap_min_true = 1e9f;
static dzframe_parser_t pp;

static float line_y(float xx) { return 0.12f * sinf(6.2831853f * xx / 2.4f); }

static void lead_send(const dzframe_t *f)
{
    uint8_t buf[DZFRAME_MAX_FRAME];
    dzframe_t g = *f;
    g.seq = lead_seq++;
    size_t n = dzframe_encode(buf, sizeof buf, &g);
    if (n && !link_cut) host_sim_uart_inject_rx(RES_UART_PEER, buf, (uint16_t)n);
}

static void lead_tick(void *ctx)  /* 50 Hz：前车一帧 */
{
    (void)ctx;
    uint8_t buf[256];
    uint16_t n;
    dzframe_t f;
    while ((n = host_sim_uart_take_tx(RES_UART_PEER, buf, sizeof buf)) > 0)      /* 后车发来的帧：只关心 ABORT */
        for (uint16_t i = 0; i < n; i++)
            if (dzframe_feed(&pp, buf[i], &f) && f.kind == DZF_DATA && f.id == PEERLINK_ID_ABORT) lead_abort_rx = true;
    if (abort_burst > 0) { abort_burst--; peerlink_abort_frame(2u, &f); lead_send(&f); return; }
    peer_state_t ps = { 0 };
    ps.t_ms = pal_millis(); ps.s_m = lead_s; ps.v_mps = lead_v;
    ps.flags = (uint16_t)((lead_brake || lead_abort_rx) && lead_v <= 0.0f ? PEER_F_STOPPED : PEER_F_RUNNING);
    peerlink_state_frame(&ps, &f);
    lead_send(&f);
}

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
    s_true += v * dt;
    for (unsigned i = 0; i < 8; i++) {
        float s = ((float)i - 3.5f) * 0.012f;
        float px = x + 0.1f * cosf(psi) + s * sinf(psi), py = y + 0.1f * sinf(psi) - s * cosf(psi);
        host_sim_gpio_set_input(ids[i], fabsf(py - line_y(px)) < 0.009f);
    }
    /* 前车运动 */
    float vt = (lead_brake || lead_abort_rx) ? 0.0f : g_link_params.v_base;
    float a = (lead_brake || lead_abort_rx) ? 2.0f : 1.0f;
    if (lead_v < vt) lead_v = fminf(vt, lead_v + a * dt); else lead_v = fmaxf(vt, lead_v - a * dt);
    lead_s += lead_v * dt;
    float g = g_link_params.gap0_m + lead_s - s_true;
    if (g < gap_min_true) gap_min_true = g;
}

void link_app_sim_cmd(uint8_t c, uint8_t n);
void link_app_sim_cmd(uint8_t c, uint8_t n)
{
    switch (c) {
    case 'O': y += (float)(int8_t)n * 0.001f; break;
    case 'B': lead_brake = true; break;
    case 'G': lead_brake = false; lead_abort_rx = false; break;
    case 'X': link_cut = true; break;
    case 'Y': link_cut = false; break;
    case 'A': abort_burst = 3; break;
    case 'Q': {
        const char *path = getenv("DZ_SIM_TRUTH");
        FILE *fp = path ? fopen(path, "w") : NULL;
        if (fp) { fprintf(fp, "gap_min_true_mm=%d lead_v=%.3f lead_s=%.3f\n", (int)lrintf(gap_min_true * 1000.0f), (double)lead_v, (double)lead_s); fclose(fp); }
        gap_min_true = 1e9f;
        break; }
    default: break;
    }
}

void host_sim_app_setup(void)
{
    host_sim_motor_t a = { RES_PWM_MOTOR_A, RES_GPIO_MOTOR_A_IN1, RES_GPIO_MOTOR_A_IN2, RES_ENCODER_MOTOR_A, 5.0f, 0.08f, 1560.0f, 0.3f, false };
    host_sim_motor_t b = a;
    b.pwm = RES_PWM_MOTOR_B; b.in1 = RES_GPIO_MOTOR_B_IN1; b.in2 = RES_GPIO_MOTOR_B_IN2; b.enc = RES_ENCODER_MOTOR_B;
    ma = host_sim_bind_motor(&a); mb = host_sim_bind_motor(&b);
    psi = atanf(0.12f * 6.2831853f / 2.4f);
    dzframe_parser_init(&pp);
    host_sim_add_periodic(1000u, plant, 0);
    host_sim_add_periodic(20000u, lead_tick, 0);   /* 20 ms */
}
