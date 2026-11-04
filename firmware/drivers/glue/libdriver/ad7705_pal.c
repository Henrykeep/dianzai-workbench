/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_ad7705_interface.h"
#include "ad7705_pal.h"

static ld_pal_bind_t g_ad7705_bind = LD_PAL_BIND_NONE;

void ad7705_pal_bind(const ld_pal_bind_t *b) { if (b) g_ad7705_bind = *b; }

uint8_t ad7705_interface_gpio_reset_init(void)
{
    return 0;
}

uint8_t ad7705_interface_gpio_reset_deinit(void)
{
    return 0;
}

uint8_t ad7705_interface_gpio_reset_write(uint8_t level)
{
    return ld_gpio_write(g_ad7705_bind.gpio[LD_AD7705_GPIO_GPIO_RESET], level);
}

uint8_t ad7705_interface_spi_init(void)
{
    return 0;
}

uint8_t ad7705_interface_spi_deinit(void)
{
    return 0;
}

uint8_t ad7705_interface_spi_read(uint8_t addr, uint8_t *buf, uint16_t len)
{
    uint8_t h = (uint8_t)addr;
    return ld_spi_frame(g_ad7705_bind.spi, &h, 1, 0, 0, buf, len);
}

uint8_t ad7705_interface_spi_write(uint8_t addr, uint8_t *buf, uint16_t len)
{
    uint8_t h = (uint8_t)addr;
    return ld_spi_frame(g_ad7705_bind.spi, &h, 1, buf, len, 0, 0);
}

void ad7705_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void ad7705_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
