/* 急停 → 'R' 后设定值归零测试（host-sim，r7 motor_pos「解除后设定值停在 90°」）。
 * 上位机持续发设定值（DATA id=1，像阶跃/扫频实验那样），在不同相位注入 ESTOP，再在不同相位发 'R'。
 * 场景 m = k % 4：0 急停后不再发；1 锁存期间继续发直到 'R'；2 同 1 且 'R' 前同一批字节里还夹一帧设定值；
 *                 3 ESTOP 后同一批字节里紧跟一帧设定值。
 * 检查：锁存 50 ms 后到 'R' 之间、以及 'R' 后 1 s 内，遥测里所有设定值通道 == 0、u 通道 == 0；'R' 后 1 s PWM 不变（不动）。
 * 用法：estop_sp <k> <types> <flags> <sp值>；types 每字段一个字符 I=u32 H=u16 B=u8 f=f32（不含 t_ms），
 *       flags 同长，s=设定值 u=输出 -=不查。输出 "k latch_sp_bad clear_sp_bad u_bad pwm_bad n_telem latch_to_sp0_us"。 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "board_gen.h"
#include "host_sim.h"
#include "app.h"
#include "dzframe.h"
#include "dzctl.h"
#include "link_gen.h"
void host_sim_app_setup(void);
static dzframe_parser_t P;
static const char *T, *F;
static int phase;            /* 0 急停前，1 锁存中（未满 50 ms），2 锁存中，3 'R' 后 */
static int latch_bad, clear_bad, u_bad, n_tel;
static long long t_inj = -1, t_zero = -1;   /* ESTOP 注入时刻；之后第一帧设定值全 0（且此后不再非 0）的遥测时刻 */
static void sendf(dzframe_t *f) { uint8_t b[DZFRAME_MAX_FRAME]; size_t n = dzframe_encode(b, sizeof b, f); host_sim_uart_inject_rx(RES_UART_LINK, b, (uint16_t)n); }
static void send_sp(float v) { dzframe_t f = {0}; f.kind = DZF_DATA; f.id = 1; dzframe_put_f32(&f, v); dzframe_put_f32(&f, 0.0f); sendf(&f); }
static void hb(void) { dzframe_t h = {0}; h.kind = DZF_HEARTBEAT; sendf(&h); }
static void check(const dzframe_t *f)
{
    size_t o = 4; int nz = 0;
    for (size_t i = 0; T[i]; i++) {
        float v = 0;
        switch (T[i]) {
        case 'I': o += 4; continue;
        case 'H': o += 2; continue;
        case 'B': o += 1; continue;
        default: if (o + 4 > f->len) return; v = dzframe_get_f32(f, o); o += 4;
        }
        if (F[i] == 's' && v != 0.0f) nz = 1;
        if (phase >= 2 && F[i] == 's' && v != 0.0f) { if (phase == 2) latch_bad++; else clear_bad++; }
        if (phase >= 2 && F[i] == 'u' && v != 0.0f) u_bad++;
    }
    if (phase >= 1 && phase < 3) { if (nz) t_zero = -1; else if (t_zero < 0) t_zero = (long long)host_sim_now_us(); }
    if (phase >= 2) n_tel++;
}
static void drain(void)
{
    uint8_t b[512]; uint16_t n; dzframe_t f;
    while ((n = host_sim_uart_take_tx(RES_UART_LINK, b, sizeof b)) > 0)
        for (uint16_t i = 0; i < n; i++) if (dzframe_feed(&P, b[i], &f) && f.kind == DZF_DATA && f.id == LINK_TELEM_ID) check(&f);
}
static void tick_ms(void) { app_loop(); drain(); for (int s = 0; s < 10; s++) { host_sim_run_us(100); drain(); } }
int main(int argc, char **argv)
{
    if (argc < 5) return 2;
    int k = atoi(argv[1]), m = k % 4; T = argv[2]; F = argv[3]; float V = (float)atof(argv[4]);
    host_sim_reset(); host_sim_set_reset_cause(PAL_RESET_POWER_ON); host_sim_app_setup();
    if (pal_init() != DZ_OK || app_init() != DZ_OK) { fprintf(stderr, "init fail\n"); return 2; }
    long long es_ms = 1000 + (k * 37) % 700, r_ms = es_ms + 200 + (k * 53) % 500;
    for (long long ms = 0; ms < r_ms + 1000; ms++) {
        if (ms % 50 == 0) hb();
        int streaming = ms < es_ms || ((m == 1 || m == 2) && ms < r_ms);
        if (ms % 20 == (k % 20) && streaming) send_sp(V);
        if (ms == es_ms) { dzframe_t e = {0}; e.kind = DZF_DATA; e.id = DZCTL_ID_ESTOP; sendf(&e); t_inj = (long long)host_sim_now_us(); if (m == 3) send_sp(V); phase = 1; }
        if (ms == es_ms + 50) phase = 2;
        if (ms == r_ms) {
            if (m == 2) send_sp(V);
            dzframe_t c = {0}; c.kind = DZF_DATA; c.id = DZCTL_ID_CMD; c.payload[0] = 'R'; c.len = 1; sendf(&c);
            phase = 3;
        }
        tick_ms();
    }
    /* 不动：再跑 1 s，PWM（蜂鸣器除外）必须和 'R' 后 1 s 末一致，且上面的遥测已查过 */
    uint16_t snap[BOARD_PWM_COUNT]; int pwm_bad = 0;
    for (unsigned i = 0; i < BOARD_PWM_COUNT; i++) snap[i] = host_sim_pwm_duty((pal_id_t)i);
    for (int ms = 0; ms < 1000; ms++) {
        if (ms % 50 == 0) hb();
        tick_ms();
        for (unsigned i = 0; i < BOARD_PWM_COUNT; i++) {
#ifdef RES_PWM_BUZZER_PWM
            if (i == (unsigned)RES_PWM_BUZZER_PWM) continue;
#endif
            if (host_sim_pwm_duty((pal_id_t)i) != snap[i]) pwm_bad++;
        }
    }
    printf("%d %d %d %d %d %d %lld\n", k, latch_bad, clear_bad, u_bad, pwm_bad, n_tel, t_zero < 0 ? -1 : t_zero - t_inj);
    return 0;
}
