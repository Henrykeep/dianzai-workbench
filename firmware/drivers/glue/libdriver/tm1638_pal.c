/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_tm1638_interface.h"
#include "tm1638_pal.h"

static ld_pal_bind_t g_tm1638_bind = LD_PAL_BIND_NONE;

void tm1638_pal_bind(const ld_pal_bind_t *b) { if (b) g_tm1638_bind = *b; }

uint8_t tm1638_interface_spi_init(void)
{
    return 0;
}

uint8_t tm1638_interface_spi_deinit(void)
{
    return 0;
}

uint8_t tm1638_interface_spi_write(uint8_t addr, uint8_t *buf, uint16_t len)
{
    uint8_t h = (uint8_t)addr;
    return ld_spi_frame(g_tm1638_bind.spi, &h, 1, buf, len, 0, 0);
}

uint8_t tm1638_interface_spi_read(uint8_t addr, uint8_t *buf, uint16_t len)
{
    uint8_t h = (uint8_t)addr;
    return ld_spi_frame(g_tm1638_bind.spi, &h, 1, 0, 0, buf, len);
}

void tm1638_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void tm1638_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
