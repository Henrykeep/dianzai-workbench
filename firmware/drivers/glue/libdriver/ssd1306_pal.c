/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_ssd1306_interface.h"
#include "ssd1306_pal.h"

static ld_pal_bind_t g_ssd1306_bind = LD_PAL_BIND_NONE;

void ssd1306_pal_bind(const ld_pal_bind_t *b) { if (b) g_ssd1306_bind = *b; }

uint8_t ssd1306_interface_iic_init(void)
{
    return 0;
}

uint8_t ssd1306_interface_iic_deinit(void)
{
    return 0;
}

uint8_t ssd1306_interface_iic_write(uint8_t addr, uint8_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_write(g_ssd1306_bind.i2c, addr, reg, buf, len);
}

uint8_t ssd1306_interface_spi_init(void)
{
    return 0;
}

uint8_t ssd1306_interface_spi_deinit(void)
{
    return 0;
}

uint8_t ssd1306_interface_spi_write_cmd(uint8_t *buf, uint16_t len)
{
    return ld_spi_frame(g_ssd1306_bind.spi, 0, 0, buf, len, 0, 0);
}

void ssd1306_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void ssd1306_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}

uint8_t ssd1306_interface_spi_cmd_data_gpio_init(void)
{
    return 0;
}

uint8_t ssd1306_interface_spi_cmd_data_gpio_deinit(void)
{
    return 0;
}

uint8_t ssd1306_interface_spi_cmd_data_gpio_write(uint8_t value)
{
    return ld_gpio_write(g_ssd1306_bind.gpio[LD_SSD1306_GPIO_SPI_CMD_DATA], value);
}

uint8_t ssd1306_interface_reset_gpio_init(void)
{
    return 0;
}

uint8_t ssd1306_interface_reset_gpio_deinit(void)
{
    return 0;
}

uint8_t ssd1306_interface_reset_gpio_write(uint8_t value)
{
    return ld_gpio_write(g_ssd1306_bind.gpio[LD_SSD1306_GPIO_RESET], value);
}
