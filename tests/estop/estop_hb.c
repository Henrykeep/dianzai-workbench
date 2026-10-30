/* 急停心跳时延测试（host-sim）：注入上位机 ESTOP 帧 → 第一帧带 DZCTL_HB_ESTOP(bit10) 的心跳，必须 ≤ 5 ms；
 * 且任何带急停原因（payload[16..19] != 0）的心跳都必须同时置 bit10。用法：estop_hb <trial>，输出 "trial latency_us bad"。
 * 与应用的 host-sim 目标文件（去掉 main_host.c.o）一起链接，见 tools/test_estop_hb.sh。 */
#include <stdio.h>
#include <stdlib.h>
#include "board_gen.h"
#include "host_sim.h"
#include "app.h"
#include "dzframe.h"
#include "dzctl.h"
void host_sim_app_setup(void);
static dzframe_parser_t P;
static long long t_inj = -1, t_hb = -1; static int bad;
static void sendf(dzframe_t *f) { uint8_t b[DZFRAME_MAX_FRAME]; size_t n = dzframe_encode(b, sizeof b, f); host_sim_uart_inject_rx(RES_UART_LINK, b, (uint16_t)n); }
static void drain(void)
{
    uint8_t b[512]; uint16_t n; dzframe_t f;
    while ((n = host_sim_uart_take_tx(RES_UART_LINK, b, sizeof b)) > 0)
        for (uint16_t i = 0; i < n; i++) if (dzframe_feed(&P, b[i], &f) && f.kind == DZF_HEARTBEAT && f.len >= 16) {
            uint32_t st = dzframe_get_u32(&f, 12);
            if (f.len >= 20 && dzframe_get_u32(&f, 16) != 0u && !(st & DZCTL_HB_ESTOP)) bad++;
            if (t_inj >= 0 && (st & DZCTL_HB_ESTOP) && t_hb < 0) t_hb = (long long)host_sim_now_us();
        }
}
int main(int argc, char **argv)
{
    int k = argc > 1 ? atoi(argv[1]) : 0;
    host_sim_reset(); host_sim_set_reset_cause(PAL_RESET_POWER_ON); host_sim_app_setup();
    if (pal_init() != DZ_OK || app_init() != DZ_OK) { fprintf(stderr, "init fail\n"); return 2; }
    long long inj_us = 1000000LL + k * 37000LL + (k % 10) * 100LL;   /* 散布在心跳相位上 */
    for (long long ms = 0; ms * 1000 < inj_us + 1000000LL; ms++) {
        if (ms % 50 == 0) { dzframe_t h = {0}; h.kind = DZF_HEARTBEAT; sendf(&h); }
        if (ms % 20 == 0 && t_inj < 0) { dzframe_t f = {0}; f.kind = DZF_DATA; f.id = 1; dzframe_put_f32(&f, 0.3f); dzframe_put_f32(&f, 0.0f); sendf(&f); }
        app_loop(); drain();
        for (int s = 0; s < 10; s++) {
            if (t_inj < 0 && (long long)host_sim_now_us() >= inj_us) {
                dzframe_t e = {0}; e.kind = DZF_DATA; e.id = DZCTL_ID_ESTOP; sendf(&e); t_inj = (long long)host_sim_now_us();
            }
            host_sim_run_us(100); drain();
        }
    }
    printf("%d %lld %d\n", k, t_hb < 0 ? -1 : t_hb - t_inj, bad);
    return 0;
}
