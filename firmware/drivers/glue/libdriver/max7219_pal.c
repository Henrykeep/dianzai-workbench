/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_max7219_interface.h"
#include "max7219_pal.h"

static ld_pal_bind_t g_max7219_bind = LD_PAL_BIND_NONE;

void max7219_pal_bind(const ld_pal_bind_t *b) { if (b) g_max7219_bind = *b; }

uint8_t max7219_interface_spi_init(void)
{
    return 0;
}

uint8_t max7219_interface_spi_deinit(void)
{
    return 0;
}

uint8_t max7219_interface_spi_write_cmd(uint8_t *buf, uint16_t len)
{
    return ld_spi_frame(g_max7219_bind.spi, 0, 0, buf, len, 0, 0);
}

uint8_t max7219_interface_spi_write(uint8_t reg, uint8_t *buf, uint16_t len)
{
    uint8_t h = (uint8_t)reg;
    return ld_spi_frame(g_max7219_bind.spi, &h, 1, buf, len, 0, 0);
}

void max7219_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void max7219_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
