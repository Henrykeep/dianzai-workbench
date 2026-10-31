/* 2026H_ball host-sim：走真实的 #38 阶跃路径（DATA 0x7B，同 tools/dzstep.py / 侧车 iterate）。
 * 每个 pos_k 一个全新仿真：PARAM_SET pos_k → DATA id=1 目标 0（必须被接收：协调器自动进 RUNNING）→ 等钢珠回到 0±6 px 持续 0.3 s（≤8 s）
 * → 0x7B 开始（ch 0，目标 60 px，dur 5000 ms）→ 收 step_result。实验期间记 |摆杆角| 最大值与协调器状态。
 * 用法：ball_step7b pos_k；输出一行：
 *   "pos_k=… ack=… sp_ok=… ret_s=… started=… aborted=… y0=… os=… rise_ms=… settle_ms=… ss=… usat=… angle_max=… run_all=…"
 * 与应用 host-sim 目标文件（去掉 main_host.c.o）一起链接，见 tools/test_ball_param.sh。 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "board_gen.h"
#include "host_sim.h"
#include "app.h"
#include "dzframe.h"
#include "dzctl.h"
#include "dzstep.h"
#include "project_gen.h"
#include "link_gen.h"
void host_sim_app_setup(void);
shared_state_t *io_state(void);
coord_t *io_coord(void);
static dzframe_parser_t P;
static int ack_status = -1, step_ack = -1, have_res;
static dzframe_t res;
static long long ms_now;
static void sendf(dzframe_t *f) { uint8_t b[DZFRAME_MAX_FRAME]; size_t n = dzframe_encode(b, sizeof b, f); host_sim_uart_inject_rx(RES_UART_LINK, b, (uint16_t)n); }
static void drain(void)
{
    uint8_t b[512]; uint16_t n; dzframe_t f;
    while ((n = host_sim_uart_take_tx(RES_UART_LINK, b, sizeof b)) > 0)
        for (uint16_t i = 0; i < n; i++) {
            if (!dzframe_feed(&P, b[i], &f)) continue;
            if (f.kind == DZF_PARAM_ACK && f.len >= 1) ack_status = f.payload[0];
            if (f.kind == DZF_DATA && f.id == DZSTEP_ID && f.len == DZSTEP_ACK_LEN) step_ack = f.payload[0];
            if (f.kind == DZF_DATA && f.id == DZSTEP_ID && f.len == DZSTEP_RESULT_LEN) { res = f; have_res = 1; }
        }
}
static void tick(int send_sp, float sp)
{
    if (ms_now % 250 == 0) { dzframe_t h = {0}; h.kind = DZF_HEARTBEAT; sendf(&h); }
    if (send_sp && ms_now % 100 == 0) { dzframe_t f = {0}; f.kind = DZF_DATA; f.id = 1; dzframe_put_f32(&f, sp); sendf(&f); }
    app_loop(); drain(); host_sim_run_us(1000); drain(); ms_now++;
}
static int pid(const char *name) { for (int i = 0; i < (int)LINK_N_PARAMS; i++) if (!strcmp(g_link_param_desc[i].name, name)) return i; return -1; }
static long u32or(const dzframe_t *f, unsigned o) { uint32_t v = dzframe_get_u32(f, o); return v == DZSTEP_NONE ? -1L : (long)v; }
int main(int argc, char **argv)
{
    float pk = argc > 1 ? (float)atof(argv[1]) : 0.72f, tgt = 60.0f;
    host_sim_reset(); host_sim_set_reset_cause(PAL_RESET_POWER_ON); host_sim_app_setup();
    if (pal_init() != DZ_OK || app_init() != DZ_OK) { fprintf(stderr, "init fail\n"); return 2; }
    for (int k = 0; k < 500; k++) tick(0, 0);
    { dzframe_t f = {0}; f.kind = DZF_PARAM_SET; f.id = (uint8_t)pid("pos_k"); dzframe_put_f32(&f, pk); sendf(&f); }
    for (int k = 0; k < 50; k++) tick(0, 0);
    int ack = ack_status;                          /* 0 = 写入成功（DZCTL_REJECTED = 5） */
    int ret = -1, in = 0, sp_ok = 0;
    for (int k = 0; k < 8000; k++) {               /* 目标 0：被接收 = 协调器进 RUNNING；等钢珠到 0±6 px 持续 0.3 s */
        tick(1, 0.0f);
        if (k == 200) sp_ok = coord_state(io_coord()) == COORD_RUNNING;
        in = fabsf(io_state()->io_in.cam_x_px) <= 6.0f ? in + 1 : 0;
        if (in >= 300) { ret = k - 299; break; }
    }
    dzframe_t s = {0}; s.kind = DZF_DATA; s.id = DZSTEP_ID;
    (void)(dzframe_put_u8(&s, 0) && dzframe_put_u8(&s, 0) && dzframe_put_u16(&s, 1) && dzframe_put_f32(&s, tgt) && dzframe_put_u32(&s, 5000u));
    sendf(&s);
    float amax = 0.0f; int run_all = 1;
    for (int k = 0; k < 6000 && !have_res; k++) {
        tick(0, 0);
        float a = fabsf(io_state()->beam_out.angle_deg); if (a > amax) amax = a;
        if (coord_state(io_coord()) != COORD_RUNNING) run_all = 0;
    }
    if (!have_res) { printf("pos_k=%.3g ack=%d sp_ok=%d ret_s=%.3f started=%d no_result\n", pk, ack, sp_ok, ret < 0 ? -1.0 : ret / 1000.0, step_ack); return 0; }
    printf("pos_k=%.3g ack=%d sp_ok=%d ret_s=%.3f started=%d aborted=%u y0=%.1f os=%.2f rise_ms=%ld settle_ms=%ld ss=%.2f usat=%.3f angle_max=%.2f run_all=%d board_pos_k=%.4g\n",
           pk, ack, sp_ok, ret < 0 ? -1.0 : ret / 1000.0, step_ack, res.payload[2], dzframe_get_f32(&res, 20), dzframe_get_f32(&res, 24),
           u32or(&res, 28), u32or(&res, 32), dzframe_get_f32(&res, 36), dzframe_get_f32(&res, 40), amax, run_all, g_project_params[0].pos_k);
    return 0;
}
