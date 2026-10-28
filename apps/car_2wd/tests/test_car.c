/* car_2wd 闭环仿真测试（电脑上跑，host-sim 两个电机模型）：指令 -> 双轮闭环 -> 遥测，断线停车。 */
#include <stdio.h>
#include <math.h>
#include "board_gen.h"
#include "host_sim.h"
#include "app.h"
#include "dzframe.h"

void host_sim_app_setup(void);
static int fails;
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
        for (uint16_t k = 0; k < n; k++)
            if (dzframe_feed(&p, b[k], &f) && f.kind == DZF_DATA && f.id == 2 && f.len == 24) {
                for (int j = 0; j < 4; j++) t[j] = dzframe_get_f32(&f, 4 + 4 * (size_t)j);
                CHECK(dzframe_get_u32(&f, 20) == 0);   /* ctrl_err */
                frames++;
            }
    }
    return frames;
}

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

    printf(fails ? "car_2wd: %d 项失败\n" : "car_2wd: 全部通过\n", fails);
    return fails != 0;
}
