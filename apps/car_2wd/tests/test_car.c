/* car_2wd 闭环仿真测试（电脑上跑，host-sim 两个电机模型）：指令 -> 双轮闭环 -> 遥测，断线停车。 */
#include <stdio.h>
#include <math.h>
#include "board_gen.h"
#include "host_sim.h"
#include "app.h"
#include "dzframe.h"
#include "dzctl.h"

void host_sim_app_setup(void);
static int fails;
static uint32_t hb_status = 0xFFFFFFFFu;
static uint16_t bb_codes[64]; static int bb_n;   /* 黑匣子导出收到的事件码 */   /* 最近一次心跳的 status 字（dzctl 0.5.0） */
#define CHECK(c) do { if (!(c)) { fails++; printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

static void send_cmd(float v, float w)
{
    dzframe_t f = { .kind = DZF_DATA, .id = 1 };
    dzframe_put_f32(&f, v); dzframe_put_f32(&f, w);
    uint8_t b[DZFRAME_MAX_FRAME]; size_t n = dzframe_encode(b, sizeof b, &f);
    host_sim_uart_inject_rx(RES_UART_LINK, b, (uint16_t)n);
}

/* 跑 ms 毫秒；cmd 为真时每 50 ms 发一次指令；返回期间最后一帧遥测 */
static int run(uint32_t ms, bool cmd, float v, float w, float t[4])
{
    static dzframe_parser_t p; static bool pi;
    if (!pi) { dzframe_parser_init(&p); pi = true; }
    int frames = 0;
    for (uint32_t i = 0; i < ms; i++) {
        if (cmd && i % 50u == 0) send_cmd(v, w);
        host_sim_run_us(1000);
        app_loop();
        uint8_t b[256]; uint16_t n = host_sim_uart_take_tx(RES_UART_LINK, b, sizeof b);
        dzframe_t f;
        for (uint16_t k = 0; k < n; k++) {
            if (!dzframe_feed(&p, b[k], &f)) continue;   /* 没出完整帧时 f 是上一帧：不能往下判 */
            if (f.kind == DZF_DATA && f.id == 2 && f.len == 24) {
                for (int j = 0; j < 4; j++) t[j] = dzframe_get_f32(&f, 4 + 4 * (size_t)j);
                CHECK(dzframe_get_u32(&f, 20) == 0);   /* ctrl_err */
                frames++;
            } else if (f.kind == DZF_HEARTBEAT && f.len >= 16u) hb_status = dzframe_get_u32(&f, 12);
            else if (f.kind == DZF_DATA && f.id == 0x7D && f.len == 16u && bb_n < 64) bb_codes[bb_n++] = dzframe_get_u16(&f, 4);
        }
    }
    return frames;
}

/* 板上分压 1:11、3.3 V 12 位 ADC（与 battery_cfg_default 一致） */
static void send_reset(void)
{
    dzframe_t f = { .kind = DZF_DATA, .id = 0x7E };
    dzframe_put_u8(&f, 'R');
    uint8_t b[DZFRAME_MAX_FRAME]; size_t n = dzframe_encode(b, sizeof b, &f);
    host_sim_uart_inject_rx(RES_UART_LINK, b, (uint16_t)n);
}

static void send_frame(dzframe_t *f)
{
    uint8_t b[DZFRAME_MAX_FRAME]; size_t n = dzframe_encode(b, sizeof b, f);
    host_sim_uart_inject_rx(RES_UART_LINK, b, (uint16_t)n);
}
static void set_param(uint8_t idx, float v) { dzframe_t f = { .kind = DZF_PARAM_SET, .id = idx }; dzframe_put_f32(&f, v); send_frame(&f); }
static int bb_has(uint16_t code) { for (int i = 0; i < bb_n; i++) if (bb_codes[i] == code) return 1; return 0; }
/* 电流采样：3.3 V 12 位、灵敏度 500 mV/A（默认参数）→ raw */
static uint16_t amp_raw(float a) { return (uint16_t)(a * 500.0f / 3300.0f * 4095.0f + 0.5f); }

static uint16_t vbat_raw(float mv_pack) { return (uint16_t)(mv_pack / 11.0f / 3300.0f * 4095.0f + 0.5f); }

int main(void)
{
    float t[4] = {0};   /* sp_a, spd_a, sp_b, spd_b */
    host_sim_reset();
    host_sim_app_setup();
    CHECK(app_init() == DZ_OK);

    /* 直行 0.4 m/s：轮径 65 mm -> 约 1.96 转/秒，两轮跟上 */
    CHECK(run(2000, true, 0.4f, 0.0f, t) > 50);
    CHECK(fabsf(t[0] - 1.959f) < 0.01f && fabsf(t[2] - 1.959f) < 0.01f);
    CHECK(fabsf(t[1] - t[0]) < 0.1f && fabsf(t[3] - t[2]) < 0.1f);
    printf("  直行: sp=%.3f A=%.3f B=%.3f\n", t[0], t[1], t[3]);

    /* 原地左转：A(左) 反转、B(右) 正转 */
    run(1500, true, 0.0f, 3.0f, t);
    CHECK(t[1] < -0.5f && t[3] > 0.5f);
    printf("  左转: A=%.3f B=%.3f\n", t[1], t[3]);

    /* 上位机断线：200 ms 超时 + 斜坡后两轮停 */
    run(1500, false, 0, 0, t);
    CHECK(t[0] == 0.0f && t[2] == 0.0f && fabsf(t[1]) < 0.1f && fabsf(t[3]) < 0.1f);
    printf("  断线: A=%.3f B=%.3f\n", t[1], t[3]);

    /* car_aux 超声波（PAL 边沿中断）：前方 ~100 mm（回波 600 us）→ 前进指令被钳到 0；障碍移走 → 恢复 */
    float sp = -1.0f;
    for (uint32_t i = 0; i < 1500; i++) {
        if (i % 50u == 0) send_cmd(0.3f, 0.0f);
        host_sim_gpio_set_input(RES_GPIO_US_ECHO, true);  host_sim_run_us(600);
        host_sim_gpio_set_input(RES_GPIO_US_ECHO, false); host_sim_run_us(400);
        app_loop();
        uint8_t b[256]; uint16_t n = host_sim_uart_take_tx(RES_UART_LINK, b, sizeof b);
        static dzframe_parser_t p2; static bool p2i; if (!p2i) { dzframe_parser_init(&p2); p2i = true; }
        dzframe_t f;
        for (uint16_t k = 0; k < n; k++)
            if (dzframe_feed(&p2, b[k], &f) && f.kind == DZF_DATA && f.id == 2 && f.len == 24) sp = dzframe_get_f32(&f, 4);
    }
    CHECK(sp == 0.0f);
    printf("  障碍 100 mm: sp_a=%.3f\n", sp);
    run(1500, true, 0.3f, 0.0f, t);   /* 回波没了 → 超时、无效 → 不再限制 */
    CHECK(t[0] > 1.0f);
    printf("  障碍移走: sp_a=%.3f\n", t[0]);

    /* 堵转：A 轮卡死（负载远大于电机能力）→ PID 顶到 0.9 占空比、转速近零 → 500 ms 后锁急停，心跳带 STALL；
     * 卡死解除也不自己动，发 'R' 才恢复 */
    CHECK(hb_status != 0xFFFFFFFFu && (hb_status & 0xFFu) == 0u && !(hb_status & (1u << 9)));   /* 仿真复位原因 = 未知 */
    host_sim_motor_set_load(0, 50.0f);
    run(2000, true, 0.3f, 0.0f, t);
    CHECK(t[0] == 0.0f && (hb_status & (1u << 9)) && (hb_status & (1u << 10)));
    CHECK(dzctl_estop_cause() == DZCTL_ES_STALL);
    printf("  堵转: sp_a=%.3f status=0x%X\n", t[0], (unsigned)hb_status);
    host_sim_motor_set_load(0, 0.3f);
    run(1000, true, 0.3f, 0.0f, t);
    CHECK(t[0] == 0.0f);
    send_reset();
    run(1500, true, 0.3f, 0.0f, t);
    CHECK(t[0] > 1.0f && fabsf(t[1] - t[0]) < 0.2f && !(hb_status & ((1u << 9) | (1u << 10))));
    CHECK(dzctl_estop_cause() == DZCTL_ES_NONE);   /* R 清掉原因 */
    printf("  R 解除: sp_a=%.3f spd_a=%.3f\n", t[0], t[1]);
    /* 起步不误判：从静止猛给 0.6 m/s，PID 会短暂顶满 */
    run(1500, false, 0, 0, t);
    run(1500, true, 0.6f, 0.0f, t);
    CHECK(t[0] > 2.5f && !(hb_status & (1u << 9)));

    /* 黑匣子导出：上电（复位原因）、堵转、解除都在 */
    bb_n = 0;
    { dzframe_t f = { .kind = DZF_DATA, .id = 0x7D }; send_frame(&f); }
    run(50, false, 0, 0, t);
    CHECK(bb_has(1) && bb_has(2) && bb_has(4));
    printf("  黑匣子: %d 条", bb_n); for (int i = 0; i < bb_n && i < 12; i++) printf(" %u", bb_codes[i]); printf("\n");

    /* 可选电流采样（host-sim 板有 ISENSE_A/B）：stall_src=1（参数序号 6）后按电流判，占空比顶满但电流小不算堵转 */
    run(1500, false, 0, 0, t);
    set_param(6, 1.0f);
    host_sim_adc_set(RES_ADC_ISENSE_A, amp_raw(0.5f)); host_sim_adc_set(RES_ADC_ISENSE_B, amp_raw(0.5f));
    host_sim_motor_set_load(0, 50.0f);
    run(2000, true, 0.3f, 0.0f, t);
    CHECK(t[0] > 1.0f && !(hb_status & (1u << 9)));       /* 0.5 A < 2 A：不判（这就是“电流模式”的意义：卡住但电流不大说明不是堵转） */
    host_sim_adc_set(RES_ADC_ISENSE_A, amp_raw(3.0f));
    run(2000, true, 0.3f, 0.0f, t);
    CHECK(t[0] == 0.0f && (hb_status & (1u << 9)));        /* 3 A + 不转：堵转 */
    printf("  电流模式堵转: sp_a=%.3f status=0x%X\n", t[0], (unsigned)hb_status);
    host_sim_motor_set_load(0, 0.3f);
    host_sim_adc_set(RES_ADC_ISENSE_A, amp_raw(0.0f)); host_sim_adc_set(RES_ADC_ISENSE_B, amp_raw(0.0f));
    set_param(6, 0.0f);
    send_reset();
    run(1500, true, 0.3f, 0.0f, t);
    CHECK(t[0] > 1.0f);

    /* car_aux 电池：先见过 OK（8.2 V，2S）再掉到 CRIT（6.0 V）→ 锁急停，之后再发前进指令也不动；电压回升也不自动解除 */
    host_sim_adc_set(RES_ADC_VBAT, vbat_raw(8200.0f));
    run(3000, true, 0.3f, 0.0f, t);
    CHECK(t[0] > 1.0f);
    host_sim_adc_set(RES_ADC_VBAT, vbat_raw(6000.0f));
    run(3000, true, 0.3f, 0.0f, t);
    CHECK(t[0] == 0.0f);
    CHECK(dzctl_estop_cause() == DZCTL_ES_UNDERVOLT);
    printf("  电池 6.0 V: sp_a=%.3f spd_a=%.3f（急停）\n", t[0], t[1]);
    host_sim_adc_set(RES_ADC_VBAT, vbat_raw(8200.0f));
    run(1500, true, 0.3f, 0.0f, t);
    CHECK(t[0] == 0.0f && fabsf(t[1]) < 0.1f);
    printf("  电压回升: sp_a=%.3f spd_a=%.3f（急停保持，只能人工解除）\n", t[0], t[1]);

    /* 安全态：上次是看门狗复位 → 上电锁急停、心跳 SAFE_BOOT + 复位原因 4；发 'R' 才走 */
    send_reset();
    host_sim_reset();
    host_sim_set_reset_cause(PAL_RESET_WATCHDOG);
    host_sim_app_setup();
    CHECK(app_init() == DZ_OK);
    run(1500, true, 0.3f, 0.0f, t);
    CHECK(t[0] == 0.0f && (hb_status & 0xFFu) == 4u && (hb_status & (1u << 8)));
    CHECK(dzctl_estop_cause() == DZCTL_ES_SAFE_BOOT);
    printf("  看门狗复位后: sp_a=%.3f status=0x%X（安全态）\n", t[0], (unsigned)hb_status);
    send_reset();
    run(1500, true, 0.3f, 0.0f, t);
    CHECK(t[0] > 1.0f && !(hb_status & (1u << 8)) && (hb_status & 0xFFu) == 4u);   /* 复位原因留着，标志清掉 */

    printf(fails ? "car_2wd: %d 项失败\n" : "car_2wd: 全部通过\n", fails);
    return fails != 0;
}
