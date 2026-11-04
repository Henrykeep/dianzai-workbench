/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_st7920_interface.h"
#include "st7920_pal.h"

static ld_pal_bind_t g_st7920_bind = LD_PAL_BIND_NONE;

void st7920_pal_bind(const ld_pal_bind_t *b) { if (b) g_st7920_bind = *b; }

uint8_t st7920_interface_cs_gpio_init(void)
{
    return 0;
}

uint8_t st7920_interface_cs_gpio_deinit(void)
{
    return 0;
}

uint8_t st7920_interface_cs_gpio_write(uint8_t value)
{
    return ld_gpio_write(g_st7920_bind.gpio[LD_ST7920_GPIO_CS], value);
}

uint8_t st7920_interface_sclk_gpio_init(void)
{
    return 0;
}

uint8_t st7920_interface_sclk_gpio_deinit(void)
{
    return 0;
}

uint8_t st7920_interface_sclk_gpio_write(uint8_t value)
{
    return ld_gpio_write(g_st7920_bind.gpio[LD_ST7920_GPIO_SCLK], value);
}

uint8_t st7920_interface_sid_gpio_init(void)
{
    return 0;
}

uint8_t st7920_interface_sid_gpio_deinit(void)
{
    return 0;
}

uint8_t st7920_interface_sid_gpio_write(uint8_t value)
{
    return ld_gpio_write(g_st7920_bind.gpio[LD_ST7920_GPIO_SID], value);
}

void st7920_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void st7920_interface_delay_us(uint32_t us)
{
    ld_delay_us(us);
}

void st7920_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
