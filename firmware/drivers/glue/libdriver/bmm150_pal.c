/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_bmm150_interface.h"
#include "bmm150_pal.h"

static ld_pal_bind_t g_bmm150_bind = LD_PAL_BIND_NONE;

void bmm150_pal_bind(const ld_pal_bind_t *b) { if (b) g_bmm150_bind = *b; }

uint8_t bmm150_interface_iic_init(void)
{
    return 0;
}

uint8_t bmm150_interface_iic_deinit(void)
{
    return 0;
}

uint8_t bmm150_interface_iic_read(uint8_t addr, uint8_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_read(g_bmm150_bind.i2c, addr, reg, buf, len);
}

uint8_t bmm150_interface_iic_write(uint8_t addr, uint8_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_write(g_bmm150_bind.i2c, addr, reg, buf, len);
}

uint8_t bmm150_interface_spi_init(void)
{
    return 0;
}

uint8_t bmm150_interface_spi_deinit(void)
{
    return 0;
}

uint8_t bmm150_interface_spi_read(uint8_t reg, uint8_t *buf, uint16_t len)
{
    uint8_t h = (uint8_t)reg;
    return ld_spi_frame(g_bmm150_bind.spi, &h, 1, 0, 0, buf, len);
}

uint8_t bmm150_interface_spi_write(uint8_t reg, uint8_t *buf, uint16_t len)
{
    uint8_t h = (uint8_t)reg;
    return ld_spi_frame(g_bmm150_bind.spi, &h, 1, buf, len, 0, 0);
}

void bmm150_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void bmm150_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}

__attribute__((weak)) void bmm150_interface_receive_callback(uint8_t type)
{
    (void)type;
}
