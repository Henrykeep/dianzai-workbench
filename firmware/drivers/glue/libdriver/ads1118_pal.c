/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_ads1118_interface.h"
#include "ads1118_pal.h"

static ld_pal_bind_t g_ads1118_bind = LD_PAL_BIND_NONE;

void ads1118_pal_bind(const ld_pal_bind_t *b) { if (b) g_ads1118_bind = *b; }

uint8_t ads1118_interface_spi_init(void)
{
    return 0;
}

uint8_t ads1118_interface_spi_deinit(void)
{
    return 0;
}

uint8_t ads1118_interface_spi_transmit(uint8_t *tx, uint8_t *rx, uint16_t len)
{
    return ld_spi_transmit(g_ads1118_bind.spi, tx, rx, len);
}

void ads1118_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void ads1118_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
