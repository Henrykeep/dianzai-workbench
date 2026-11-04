/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_hcsr04_interface.h"
#include "hcsr04_pal.h"

static ld_pal_bind_t g_hcsr04_bind = LD_PAL_BIND_NONE;

void hcsr04_pal_bind(const ld_pal_bind_t *b) { if (b) g_hcsr04_bind = *b; }

uint8_t hcsr04_interface_trig_init(void)
{
    return 0;
}

uint8_t hcsr04_interface_trig_deinit(void)
{
    return 0;
}

uint8_t hcsr04_interface_trig_write(uint8_t value)
{
    return ld_gpio_write(g_hcsr04_bind.gpio[LD_HCSR04_GPIO_TRIG], value);
}

uint8_t hcsr04_interface_echo_init(void)
{
    return 0;
}

uint8_t hcsr04_interface_echo_deinit(void)
{
    return 0;
}

uint8_t hcsr04_interface_echo_read(uint8_t *value)
{
    return ld_gpio_read(g_hcsr04_bind.gpio[LD_HCSR04_GPIO_ECHO], value);
}

uint8_t hcsr04_interface_timestamp_read(hcsr04_time_t *t)
{
    if (!t) return 1;
    ld_time_now(0, 0, &t->microsecond, &t->millisecond);
    return 0;
}

void hcsr04_interface_delay_us(uint32_t us)
{
    ld_delay_us(us);
}

void hcsr04_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void hcsr04_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
