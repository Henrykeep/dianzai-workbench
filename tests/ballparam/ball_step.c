/* 2026H_ball host-sim 阶跃回归：按 dzbench.json step_tests.2026H_ball 的做法（'T'1 'G'，pre_s 段 sp=low，再 hold_s 段 sp=high），
 * 每轮前用 PARAM_SET 写 pos_k，量本轮指标。用法：ball_step pre_s hold_s pos_k...；每轮输出一行：
 *   "round pos_k ack_ok start_err_px x_at_step overshoot_pct rise_s settle_s ss_err_px board_pos_k ret=回到 low±3px 用时 test_id=…"
 * rise/settle = -1 表示 hold_s 内没到（90% / ±5%）
 * start_err_px：阶跃时刻（pre_s 结束）钢珠离 low 的距离。与应用 host-sim 目标文件（去掉 main_host.c.o）一起链接，见 tools/test_ball_param.sh。 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "board_gen.h"
#include "host_sim.h"
#include "app.h"
#include "dzframe.h"
#include "dzctl.h"
#include "project_gen.h"
#include "link_gen.h"
void host_sim_app_setup(void);
shared_state_t *io_state(void);
coord_t *io_coord(void);
static dzframe_parser_t P; static int acks, ack_ok;
static void sendf(dzframe_t *f) { uint8_t b[DZFRAME_MAX_FRAME]; size_t n = dzframe_encode(b, sizeof b, f); host_sim_uart_inject_rx(RES_UART_LINK, b, (uint16_t)n); }
static void drain(void)
{
    uint8_t b[512]; uint16_t n; dzframe_t f;
    while ((n = host_sim_uart_take_tx(RES_UART_LINK, b, sizeof b)) > 0)
        for (uint16_t i = 0; i < n; i++) if (dzframe_feed(&P, b[i], &f) && f.kind == DZF_PARAM_ACK) { acks++; ack_ok = f.len >= 4; }
}
static long long ms_now;
static void tick(float sp, int sp_on)
{
    if (ms_now % 250 == 0) { dzframe_t h = {0}; h.kind = DZF_HEARTBEAT; sendf(&h); }
    if (sp_on && ms_now % 100 == 0) { dzframe_t f = {0}; f.kind = DZF_DATA; f.id = 1; dzframe_put_f32(&f, sp); sendf(&f); }
    app_loop(); drain(); host_sim_run_us(1000); drain(); ms_now++;
}
static void cmd(char c, int n) { dzframe_t f = {0}; f.kind = DZF_DATA; f.id = DZCTL_ID_CMD; f.payload[0] = (uint8_t)c; f.payload[1] = (uint8_t)n; f.len = n >= 0 ? 2 : 1; sendf(&f); }
static int pid(const char *name) { for (int i = 0; i < (int)LINK_N_PARAMS; i++) if (!strcmp(g_link_param_desc[i].name, name)) return i; return -1; }
int main(int argc, char **argv)
{
    float pre = argc > 1 ? (float)atof(argv[1]) : 1.0f, hold = argc > 2 ? (float)atof(argv[2]) : 4.0f, lo = 0.0f, hi = 60.0f;
    static float y[20000];
    host_sim_reset(); host_sim_set_reset_cause(PAL_RESET_POWER_ON); host_sim_app_setup();
    if (pal_init() != DZ_OK || app_init() != DZ_OK) { fprintf(stderr, "init fail\n"); return 2; }
    for (int k = 0; k < 500; k++) tick(0, 0);
    for (int r = 3; r < argc; r++) {
        float pk = (float)atof(argv[r]);
        dzframe_t f = {0}; f.kind = DZF_PARAM_SET; f.id = (uint8_t)pid("pos_k"); dzframe_put_f32(&f, pk); acks = 0; ack_ok = 0; sendf(&f);
        for (int k = 0; k < 50; k++) tick(lo, 0);
        if (coord_state(io_coord()) == COORD_DONE) { cmd('R', -1); for (int k = 0; k < 100; k++) tick(lo, 0); }
        cmd('T', 1); for (int k = 0; k < 50; k++) tick(lo, 0);
        cmd('G', -1); for (int k = 0; k < 50; k++) tick(lo, 0);
        int npre = (int)(pre * 1000), nh = (int)(hold * 1000);
        int ret = -1; for (int k = 0; k < npre; k++) { tick(lo, 1); float e = fabsf(io_state()->io_in.cam_x_px - lo); if (e > 3.0f) ret = -1; else if (ret < 0) ret = k; }
        float x0 = io_state()->io_in.cam_x_px;
        for (int k = 0; k < nh; k++) { tick(hi, 1); y[k] = io_state()->io_in.cam_x_px; if (getenv("BS_TRACE") && k % 200 == 0) fprintf(stderr, "t=%d x=%.1f sp=%.1f ang=%.2f bb=%u vis=%u cs=%d\n", k, y[k], io_state()->coord.ball_sp_px, io_state()->beam_out.angle_deg, io_state()->beam_out.state, io_state()->vision_out.state, (int)coord_state(io_coord())); }
        float span = hi - x0, pk_y = y[0]; int rise = -1, settle = 0;
        for (int k = 0; k < nh; k++) { if ((y[k] - x0) * (span > 0 ? 1 : -1) > (pk_y - x0) * (span > 0 ? 1 : -1)) pk_y = y[k]; if (rise < 0 && fabsf(y[k] - x0) >= 0.9f * fabsf(span)) rise = k; }
        for (int k = 0; k < nh; k++) if (fabsf(y[k] - hi) > 0.05f * fabsf(hi - lo)) settle = k + 1;
        float ss = 0; for (int k = nh - 300; k < nh; k++) ss += y[k] - hi; ss /= 300.0f;
        float os = 100.0f * fmaxf(0.0f, (pk_y - hi) / (hi - lo));
        printf("%d %.3g %d %.1f %.1f %.1f %.3f %.3f %.2f %.4g ret=%.3f test_id=%u\n", r - 2, pk, ack_ok, x0 - lo, x0, os, rise < 0 ? -1.0 : rise / 1000.0,
               settle >= nh ? -1.0 : settle / 1000.0, ss, g_project_params[0].pos_k, ret < 0 ? -1.0 : ret / 1000.0, io_state()->coord.test_id);
        /* 回到 low 准备下一轮（与侧车一致：只发 low 设定值，不复位） */
    }
    return 0;
}
