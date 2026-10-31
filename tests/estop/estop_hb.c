/* 急停心跳时延测试（host-sim）：注入上位机 ESTOP 帧 → 第一帧带 DZCTL_HB_ESTOP(bit10) 的心跳，必须 ≤ 5 ms；
 * 且任何带急停原因（payload[16..19] != 0）的心跳都必须同时置 bit10。用法：estop_hb <trial>，输出 "trial latency_us bad"。
 * 之后发 'R'：锁存必须解除（后续心跳 bit10 清、原因清），且 1 s 内不收新设定值时所有输出（PWM，蜂鸣器除外）保持急停时的值——不自动恢复。
 * 'R' 后第一帧 bit10 清的心跳也必须 ≤ 5 ms（急停下降沿立即发），且该帧急停原因已清。
 * 输出 "trial latency_us bad resume_bad cleared clear_latency_us clear_cause_ok"。
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
static long long t_inj = -1, t_hb = -1, t_r = -1, t_clr = -1; static int bad, cleared, clr_cause;
static void sendf(dzframe_t *f) { uint8_t b[DZFRAME_MAX_FRAME]; size_t n = dzframe_encode(b, sizeof b, f); host_sim_uart_inject_rx(RES_UART_LINK, b, (uint16_t)n); }
static void drain(void)
{
    uint8_t b[512]; uint16_t n; dzframe_t f;
    while ((n = host_sim_uart_take_tx(RES_UART_LINK, b, sizeof b)) > 0)
        for (uint16_t i = 0; i < n; i++) if (dzframe_feed(&P, b[i], &f) && f.kind == DZF_HEARTBEAT && f.len >= 16) {
            uint32_t st = dzframe_get_u32(&f, 12);
            if (f.len >= 20 && dzframe_get_u32(&f, 16) != 0u && !(st & DZCTL_HB_ESTOP)) bad++;
            if (t_r >= 0 && !(st & DZCTL_HB_ESTOP) && t_clr < 0) {   /* 'R' 后第一帧 bit10 清的心跳：记时延，且原因必须同帧已清 */
                t_clr = (long long)host_sim_now_us();
                clr_cause = (f.len < 20 || dzframe_get_u32(&f, 16) == 0u);
            }
            if (t_r >= 0 && !(st & DZCTL_HB_ESTOP) && (f.len < 20 || dzframe_get_u32(&f, 16) == 0u)) cleared = 1;
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
    /* 'R' 相对周期心跳（急停沿后重新对相）再错开 k*53 ms + 0.1 ms 级抖动，10 个相位覆盖 500 ms 周期 */
    for (int ms = 0; ms < (k * 53) % 500 + 7; ms++) {
        if (ms % 50 == 0) { dzframe_t h = {0}; h.kind = DZF_HEARTBEAT; sendf(&h); }
        app_loop(); drain();
        for (int s = 0; s < 10; s++) { host_sim_run_us(100); drain(); }
    }
    host_sim_run_us(100u * (unsigned)(k % 7)); drain();
    /* 'R' 解除：锁存清、设定值清零、输出不自动恢复 */
    uint16_t snap[BOARD_PWM_COUNT]; int resume_bad = 0;
    for (unsigned i = 0; i < BOARD_PWM_COUNT; i++) snap[i] = host_sim_pwm_duty((pal_id_t)i);
    { dzframe_t c = {0}; c.kind = DZF_DATA; c.id = DZCTL_ID_CMD; c.payload[0] = 'R'; c.len = 1; sendf(&c); t_r = (long long)host_sim_now_us(); }
    for (int ms = 0; ms < 1000; ms++) {
        if (ms % 50 == 25) {   /* 上位机心跳错开 'R'，量的是固件自己发的下降沿心跳，不是对上位机心跳的回应 */ dzframe_t h = {0}; h.kind = DZF_HEARTBEAT; sendf(&h); }
        app_loop(); drain();
        for (int s = 0; s < 10; s++) { host_sim_run_us(100); drain(); }
        for (unsigned i = 0; i < BOARD_PWM_COUNT; i++) {
#ifdef RES_PWM_BUZZER_PWM
            if (i == (unsigned)RES_PWM_BUZZER_PWM) continue;
#endif
            if (host_sim_pwm_duty((pal_id_t)i) != snap[i]) resume_bad++;
        }
    }
    printf("%d %lld %d %d %d %lld %d\n", k, t_hb < 0 ? -1 : t_hb - t_inj, bad, resume_bad, cleared, t_clr < 0 ? -1 : t_clr - t_r, clr_cause);
    return 0;
}
