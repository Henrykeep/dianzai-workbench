/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_max6675_interface.h"
#include "max6675_pal.h"

static ld_pal_bind_t g_max6675_bind = LD_PAL_BIND_NONE;

void max6675_pal_bind(const ld_pal_bind_t *b) { if (b) g_max6675_bind = *b; }

uint8_t max6675_interface_spi_init(void)
{
    return 0;
}

uint8_t max6675_interface_spi_deinit(void)
{
    return 0;
}

uint8_t max6675_interface_spi_read_cmd(uint8_t *buf, uint16_t len)
{
    return ld_spi_frame(g_max6675_bind.spi, 0, 0, 0, 0, buf, len);
}

void max6675_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void max6675_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
