/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_st7789_interface.h"
#include "st7789_pal.h"

static ld_pal_bind_t g_st7789_bind = LD_PAL_BIND_NONE;

void st7789_pal_bind(const ld_pal_bind_t *b) { if (b) g_st7789_bind = *b; }

uint8_t st7789_interface_spi_init(void)
{
    return 0;
}

uint8_t st7789_interface_spi_deinit(void)
{
    return 0;
}

uint8_t st7789_interface_spi_write_cmd(uint8_t *buf, uint16_t len)
{
    return ld_spi_frame(g_st7789_bind.spi, 0, 0, buf, len, 0, 0);
}

void st7789_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void st7789_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}

uint8_t st7789_interface_cmd_data_gpio_init(void)
{
    return 0;
}

uint8_t st7789_interface_cmd_data_gpio_deinit(void)
{
    return 0;
}

uint8_t st7789_interface_cmd_data_gpio_write(uint8_t value)
{
    return ld_gpio_write(g_st7789_bind.gpio[LD_ST7789_GPIO_CMD_DATA], value);
}

uint8_t st7789_interface_reset_gpio_init(void)
{
    return 0;
}

uint8_t st7789_interface_reset_gpio_deinit(void)
{
    return 0;
}

uint8_t st7789_interface_reset_gpio_write(uint8_t value)
{
    return ld_gpio_write(g_st7789_bind.gpio[LD_ST7789_GPIO_RESET], value);
}
