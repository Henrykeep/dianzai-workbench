/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_tm1640_interface.h"
#include "tm1640_pal.h"

static ld_pal_bind_t g_tm1640_bind = LD_PAL_BIND_NONE;

void tm1640_pal_bind(const ld_pal_bind_t *b) { if (b) g_tm1640_bind = *b; }

uint8_t tm1640_interface_sclk_gpio_init(void)
{
    return 0;
}

uint8_t tm1640_interface_sclk_gpio_deinit(void)
{
    return 0;
}

uint8_t tm1640_interface_sclk_gpio_write(uint8_t level)
{
    return ld_gpio_write(g_tm1640_bind.gpio[LD_TM1640_GPIO_SCLK], level);
}

uint8_t tm1640_interface_din_gpio_init(void)
{
    return 0;
}

uint8_t tm1640_interface_din_gpio_deinit(void)
{
    return 0;
}

uint8_t tm1640_interface_din_gpio_write(uint8_t level)
{
    return ld_gpio_write(g_tm1640_bind.gpio[LD_TM1640_GPIO_DIN], level);
}

void tm1640_interface_delay_us(uint32_t us)
{
    ld_delay_us(us);
}

void tm1640_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void tm1640_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
