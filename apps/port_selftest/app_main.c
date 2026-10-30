/**
 * @file app_main.c
 * @brief 移植层上板自检。只用 PAL 接口与 board_gen.h 的计数宏，适用于任何移植层。
 *
 * 输出（LINK 串口，每 1 s 一份）：
 *   ST time  ok|FAIL  micros/millis 一致性、delay_us 误差
 *   ST timer ok|FAIL  CTRL 1 kHz 回调实际次数
 *   ST pwm/enc/adc/dac    每个资源调用结果（PWM 依次扫 0/50/100% 占空比，用示波器看）
 *   ST uart dropped=  LINK 接收丢字节数；收到的字节原样回显（串口助手发什么回什么）
 * 判定靠人看示波器/串口助手；本固件只保证“每个 PAL 接口都被调用过且返回值被打印”。
 */
#include <stdio.h>
#include <string.h>
#include "board_gen.h"
#include "app.h"
#include "pal.h"
#include "link_io.h"

static volatile uint32_t s_ticks;
static void on_ctrl(void *ctx) { (void)ctx; s_ticks++; }

static void say(const char *s)
{
    uint16_t n = (uint16_t)strlen(s);
    bool idle = false;
    uint32_t t0 = pal_millis();
    while (link_tx_idle(&idle) == DZ_OK && !idle && pal_millis() - t0 < 50u) { }
    (void)link_write((const uint8_t *)s, n);
}

static void test_time(char *b, size_t n)
{
    uint32_t m0 = pal_millis(), u0 = pal_micros();
    pal_delay_us(5000u);
    uint32_t du = pal_micros() - u0, dm = pal_millis() - m0;
    bool ok = du >= 5000u && du < 5300u && dm >= 4u && dm <= 6u;
    snprintf(b, n, "ST time  %s delay_us(5000)->micros %lu, millis %lu\r\n",
             ok ? "ok" : "FAIL", (unsigned long)du, (unsigned long)dm);
}

dz_err_t app_init(void)
{
    return pal_timer_start(RES_TIMER_CTRL, 1000u, on_ctrl, 0);
}

void app_loop(void)
{
    static uint32_t last = 0, step = 0, ticks0 = 0;
    char b[128];
    uint8_t rx[32]; uint16_t got = 0;

    if (link_read(rx, sizeof rx, &got) == DZ_OK && got)
        (void)link_write(rx, got);       /* 回显 */

    uint32_t now = pal_millis();
    if (now - last < 1000u) return;
    last = now;
    step++;

    snprintf(b, sizeof b, "\r\n== port_selftest %s #%lu ==\r\n", pal_board_name(), (unsigned long)step); say(b);
    test_time(b, sizeof b); say(b);
    uint32_t t = s_ticks, dt = t - ticks0; ticks0 = t;
    if (step > 1) { snprintf(b, sizeof b, "ST timer %s %lu/1000 callbacks\r\n",
                             (dt >= 995u && dt <= 1005u) ? "ok" : "FAIL", (unsigned long)dt); say(b); }

#if BOARD_GPIO_COUNT > 0
    for (pal_id_t i = 0; i < BOARD_GPIO_COUNT; i++) {
        bool v = false;
        dz_err_t e = pal_gpio_read(i, &v);
        snprintf(b, sizeof b, "ST gpio%u read=%d rc=%d\r\n", (unsigned)i, (int)v, (int)e); say(b);
    }
#endif
#ifdef RES_GPIO_LED
    (void)pal_gpio_toggle(RES_GPIO_LED);
#endif
#if BOARD_PWM_COUNT > 0
    static const uint16_t duty[3] = {0u, PAL_DUTY_MAX / 2u, PAL_DUTY_MAX};
    for (pal_id_t i = 0; i < BOARD_PWM_COUNT; i++) {
        uint32_t f = 0;
        dz_err_t e1 = pal_pwm_set_duty(i, duty[step % 3u]), e2 = pal_pwm_get_freq(i, &f);
        snprintf(b, sizeof b, "ST pwm%u duty=%u/%u freq=%luHz rc=%d,%d\r\n", (unsigned)i,
                 (unsigned)duty[step % 3u], (unsigned)PAL_DUTY_MAX, (unsigned long)f, (int)e1, (int)e2); say(b);
    }
#endif
#if BOARD_ENCODER_COUNT > 0
    for (pal_id_t i = 0; i < BOARD_ENCODER_COUNT; i++) {
        int32_t c = 0; dz_err_t e = pal_enc_get_count(i, &c);
        snprintf(b, sizeof b, "ST enc%u count=%ld rc=%d (手转电机看增减方向)\r\n", (unsigned)i, (long)c, (int)e); say(b);
    }
#endif
#if BOARD_ADC_COUNT > 0
    for (pal_id_t i = 0; i < BOARD_ADC_COUNT; i++) {
        uint16_t r = 0; dz_err_t e = pal_adc_read(i, &r);
        snprintf(b, sizeof b, "ST adc%u raw=%u rc=%d\r\n", (unsigned)i, (unsigned)r, (int)e); say(b);
    }
#endif
#if BOARD_DAC_COUNT > 0
    for (pal_id_t i = 0; i < BOARD_DAC_COUNT; i++) {
        pal_dac_info_t di = {0}; dz_err_t e = pal_dac_info(i, &di);
        uint16_t mid = (uint16_t)(di.bits ? (1u << (di.bits - 1u)) : 0u);
        if (e == DZ_OK) e = pal_dac_write(i, mid);
        snprintf(b, sizeof b, "ST dac%u code=%u rc=%d (万用表应读约 %lu mV)\r\n", (unsigned)i, (unsigned)mid, (int)e,
                 (unsigned long)(di.vref_mv / 2u)); say(b);
    }
#endif
    uint32_t d = 0; (void)pal_uart_rx_dropped(RES_UART_LINK, &d);
    snprintf(b, sizeof b, "ST uart dropped=%lu (发送任意字符应被回显)\r\n", (unsigned long)d); say(b);
}
