/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_max31865_interface.h"
#include "max31865_pal.h"

static ld_pal_bind_t g_max31865_bind = LD_PAL_BIND_NONE;

void max31865_pal_bind(const ld_pal_bind_t *b) { if (b) g_max31865_bind = *b; }

uint8_t max31865_interface_spi_init(void)
{
    return 0;
}

uint8_t max31865_interface_spi_deinit(void)
{
    return 0;
}

uint8_t max31865_interface_spi_read(uint8_t reg, uint8_t *buf, uint16_t len)
{
    uint8_t h = (uint8_t)reg;
    return ld_spi_frame(g_max31865_bind.spi, &h, 1, 0, 0, buf, len);
}

uint8_t max31865_interface_spi_write(uint8_t reg, uint8_t *buf, uint16_t len)
{
    uint8_t h = (uint8_t)reg;
    return ld_spi_frame(g_max31865_bind.spi, &h, 1, buf, len, 0, 0);
}

void max31865_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void max31865_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
