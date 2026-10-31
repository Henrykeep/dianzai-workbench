/* #38 阶跃实验 host-sim 驱动（真实应用代码 + host-sim 对象）。tools/test_step_result.py 编译并驱动它。
 * stdin 一行一条脚本（按 ms 升序）：
 *   <ms> step <ch> <iter> <target> <dur_ms>   开始阶跃（DATA 0x7B len 12）
 *   <ms> stop                                 停止阶跃（DATA 0x7B len 0）
 *   <ms> sp <v>                               设定值 DATA id=1（1 个 f32）
 *   <ms> estop | <ms> R | <ms> cmd <c>        急停 / 解除 / 单字节命令（如 U 扶正摆）
 *   <ms> param <idx> <value>                  PARAM_SET 写
 *   <ms> relay <loop> <amp> <hyst> <timeout_s> | <ms> relaystop   0x7C 继电开始 / 停止
 *   <ms> end                                  结束
 * 上位机心跳每 50 ms 自动发。stdout 每个板发出的帧一行："<ms> <kind> <id> <payload hex>"。
 * 另：开头一行 "CRC <params_crc32>"（默认参数），用于 C↔Python 参数哈希对拍。 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "board_gen.h"
#include "host_sim.h"
#include "app.h"
#include "dzframe.h"
#include "dzctl.h"
#include "dzstep.h"
#include "link_gen.h"
void host_sim_app_setup(void);
static dzframe_parser_t P;
static long long g_ms;
static void sendf(dzframe_t *f) { uint8_t b[DZFRAME_MAX_FRAME]; size_t n = dzframe_encode(b, sizeof b, f); host_sim_uart_inject_rx(RES_UART_LINK, b, (uint16_t)n); }
static void drain(void)
{
    uint8_t b[512]; uint16_t n; dzframe_t f;
    while ((n = host_sim_uart_take_tx(RES_UART_LINK, b, sizeof b)) > 0)
        for (uint16_t i = 0; i < n; i++) if (dzframe_feed(&P, b[i], &f)) {
            printf("%lld %u %u ", g_ms, (unsigned)f.kind, (unsigned)f.id);
            for (unsigned k = 0; k < f.len; k++) printf("%02x", f.payload[k]);
            printf("\n");
        }
}
static void tick_ms(void) { app_loop(); drain(); for (int s = 0; s < 10; s++) { host_sim_run_us(100); drain(); } }
int main(void)
{
    host_sim_reset(); host_sim_set_reset_cause(PAL_RESET_POWER_ON); host_sim_app_setup();
    if (pal_init() != DZ_OK || app_init() != DZ_OK) { fprintf(stderr, "init fail\n"); return 2; }
    {
        dzctl_table_t t = link_param_table(&g_link_params);
        printf("CRC %u\n", (unsigned)dzctl_params_crc32(&t));
    }
    char line[256];
    long long at = 0; char op[16] = "";
    int have = 0;
    for (;;) {
        if (!have) {
            if (!fgets(line, sizeof line, stdin)) break;
            if (sscanf(line, "%lld %15s", &at, op) != 2) continue;
            have = 1;
        }
        while (g_ms < at) { if (g_ms % 50 == 0) { dzframe_t h = {0}; h.kind = DZF_HEARTBEAT; sendf(&h); } tick_ms(); g_ms++; }
        have = 0;
        dzframe_t f; memset(&f, 0, sizeof f); f.kind = DZF_DATA;
        if (!strcmp(op, "end")) break;
        else if (!strcmp(op, "step")) {
            unsigned ch, it, dur; float tg;
            if (sscanf(line, "%*lld %*s %u %u %f %u", &ch, &it, &tg, &dur) != 4) return 3;
            f.id = DZSTEP_ID;
            (void)(dzframe_put_u8(&f, (uint8_t)ch) && dzframe_put_u8(&f, 0) && dzframe_put_u16(&f, (uint16_t)it)
                   && dzframe_put_f32(&f, tg) && dzframe_put_u32(&f, dur));
        }
        else if (!strcmp(op, "stop")) f.id = DZSTEP_ID;
        else if (!strcmp(op, "relay")) {      /* <ms> relay <loop> <amp> <hyst> <timeout_s>：0x7C 继电开始 */
            unsigned lp; float a, h, t;
            if (sscanf(line, "%*lld %*s %u %f %f %f", &lp, &a, &h, &t) != 4) return 3;
            f.id = DZCTL_ID_RELAY;
            (void)(dzframe_put_u8(&f, (uint8_t)lp) && dzframe_put_f32(&f, a) && dzframe_put_f32(&f, h) && dzframe_put_f32(&f, t));
        }
        else if (!strcmp(op, "relaystop")) f.id = DZCTL_ID_RELAY;
        else if (!strcmp(op, "sp")) { float v; if (sscanf(line, "%*lld %*s %f", &v) != 1) return 3; f.id = 1; dzframe_put_f32(&f, v); }
        else if (!strcmp(op, "vw")) { float v, w; if (sscanf(line, "%*lld %*s %f %f", &v, &w) != 2) return 3; f.id = 1; dzframe_put_f32(&f, v); dzframe_put_f32(&f, w); }
        else if (!strcmp(op, "estop")) f.id = DZCTL_ID_ESTOP;
        else if (!strcmp(op, "R") || !strcmp(op, "cmd")) {
            char c = 'R'; if (op[0] == 'c' && sscanf(line, "%*lld %*s %c", &c) != 1) return 3;
            f.id = DZCTL_ID_CMD; dzframe_put_u8(&f, (uint8_t)c);
        }
        else if (!strcmp(op, "param")) {
            unsigned i; float v; char vs[32];
            if (sscanf(line, "%*lld %*s %u %31s", &i, vs) != 2) return 3;
            v = strtof(vs, 0);   /* "nan" / "inf" 也认 */
            f.kind = DZF_PARAM_SET; f.id = (uint8_t)i; dzframe_put_f32(&f, v);
        }
        else return 3;
        sendf(&f);
    }
    fflush(stdout);
    return 0;
}
