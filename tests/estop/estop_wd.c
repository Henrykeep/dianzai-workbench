/* 链路看门狗测试（host-sim，通用：任何带 LINK 的应用）：上位机每 250 ms 发心跳，中途停发 <stall_ms> 再恢复。
 * 输出 "stall_ms cause value_ms gap_ms"：cause = 心跳里的急停原因（0 = 没急停），value_ms = 急停记录里的触发值，
 * gap_ms = 测试自己量的「最后一帧上位机帧 → 第一帧带急停原因的心跳」间隔。阈值来自 link.yaml 的 watchdog_ms（LINK_WD_TIMEOUT_MS）。
 * 与应用的 host-sim 目标文件（去掉 main_host.c.o）一起链接，见 tools/test_estop_wd.sh。 */
#include <stdio.h>
#include <stdlib.h>
#include "board_gen.h"
#include "host_sim.h"
#include "app.h"
#include "dzframe.h"
#include "dzctl.h"
#include "link_gen.h"
void host_sim_app_setup(void);
static dzframe_parser_t P;
static uint32_t cause; static float value; static long long t_last_tx = -1, t_es = -1;
static void sendf(dzframe_t *f) { uint8_t b[DZFRAME_MAX_FRAME]; size_t n = dzframe_encode(b, sizeof b, f); host_sim_uart_inject_rx(RES_UART_LINK, b, (uint16_t)n); t_last_tx = (long long)host_sim_now_us(); }
static void drain(void)
{
    uint8_t b[512]; uint16_t n; dzframe_t f;
    while ((n = host_sim_uart_take_tx(RES_UART_LINK, b, sizeof b)) > 0)
        for (uint16_t i = 0; i < n; i++) if (dzframe_feed(&P, b[i], &f) && f.kind == DZF_HEARTBEAT && f.len >= 28 && !cause) {
            uint32_t c = dzframe_get_u32(&f, 16);
            if (c) { cause = c; value = dzframe_get_f32(&f, 24); t_es = (long long)host_sim_now_us(); }
        }
}
static void run_ms(int ms, int hb)
{
    for (int m = 0; m < ms; m++) {
        if (hb && m % 250 == 0) { dzframe_t h = {0}; h.kind = DZF_HEARTBEAT; sendf(&h); }
        app_loop(); drain();
        for (int s = 0; s < 10; s++) { host_sim_run_us(100); drain(); }
    }
}
int main(int argc, char **argv)
{
    int stall = argc > 1 ? atoi(argv[1]) : 0;
    host_sim_reset(); host_sim_set_reset_cause(PAL_RESET_POWER_ON); host_sim_app_setup();
    if (pal_init() != DZ_OK || app_init() != DZ_OK) { fprintf(stderr, "init fail\n"); return 2; }
    run_ms(2000, 1);
    long long last = t_last_tx;
    run_ms(stall, 0);                 /* 主机卡顿：一帧不发 */
    run_ms(1000, 1);
    printf("%d %u %.0f %lld\n", stall, (unsigned)cause, (double)value, t_es < 0 ? -1 : (t_es - last) / 1000);
    printf("LINK_WD_TIMEOUT_MS %u\n", (unsigned)LINK_WD_TIMEOUT_MS);
    return 0;
}
