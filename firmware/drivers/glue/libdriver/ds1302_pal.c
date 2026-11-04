/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_ds1302_interface.h"
#include "ds1302_pal.h"

static ld_pal_bind_t g_ds1302_bind = LD_PAL_BIND_NONE;

void ds1302_pal_bind(const ld_pal_bind_t *b) { if (b) g_ds1302_bind = *b; }

uint8_t ds1302_interface_ce_gpio_init(void)
{
    return 0;
}

uint8_t ds1302_interface_ce_gpio_deinit(void)
{
    return 0;
}

uint8_t ds1302_interface_ce_gpio_write(uint8_t value)
{
    return ld_gpio_write(g_ds1302_bind.gpio[LD_DS1302_GPIO_CE], value);
}

uint8_t ds1302_interface_sclk_gpio_init(void)
{
    return 0;
}

uint8_t ds1302_interface_sclk_gpio_deinit(void)
{
    return 0;
}

uint8_t ds1302_interface_sclk_gpio_write(uint8_t value)
{
    return ld_gpio_write(g_ds1302_bind.gpio[LD_DS1302_GPIO_SCLK], value);
}

uint8_t ds1302_interface_io_gpio_init(void)
{
    return 0;
}

uint8_t ds1302_interface_io_gpio_deinit(void)
{
    return 0;
}

uint8_t ds1302_interface_io_gpio_write(uint8_t value)
{
    return ld_gpio_write(g_ds1302_bind.gpio[LD_DS1302_GPIO_IO], value);
}

uint8_t ds1302_interface_io_gpio_read(uint8_t *value)
{
    return ld_gpio_read(g_ds1302_bind.gpio[LD_DS1302_GPIO_IO], value);
}

void ds1302_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void ds1302_interface_delay_us(uint32_t us)
{
    ld_delay_us(us);
}

void ds1302_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
