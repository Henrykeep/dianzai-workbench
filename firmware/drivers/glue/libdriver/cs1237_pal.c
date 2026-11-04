/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_cs1237_interface.h"
#include "cs1237_pal.h"

static ld_pal_bind_t g_cs1237_bind = LD_PAL_BIND_NONE;

void cs1237_pal_bind(const ld_pal_bind_t *b) { if (b) g_cs1237_bind = *b; }

uint8_t cs1237_interface_sclk_gpio_init(void)
{
    return 0;
}

uint8_t cs1237_interface_sclk_gpio_deinit(void)
{
    return 0;
}

uint8_t cs1237_interface_sclk_gpio_write(uint8_t level)
{
    return ld_gpio_write(g_cs1237_bind.gpio[LD_CS1237_GPIO_SCLK], level);
}

uint8_t cs1237_interface_dout_gpio_init(void)
{
    return 0;
}

uint8_t cs1237_interface_dout_gpio_deinit(void)
{
    return 0;
}

uint8_t cs1237_interface_dout_gpio_write(uint8_t level)
{
    return ld_gpio_write(g_cs1237_bind.gpio[LD_CS1237_GPIO_DOUT], level);
}

uint8_t cs1237_interface_dout_gpio_read(uint8_t *level)
{
    return ld_gpio_read(g_cs1237_bind.gpio[LD_CS1237_GPIO_DOUT], level);
}

void cs1237_interface_delay_us(uint32_t us)
{
    ld_delay_us(us);
}

void cs1237_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void cs1237_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
