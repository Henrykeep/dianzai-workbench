/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_ws2812b_interface.h"
#include "ws2812b_pal.h"

static ld_pal_bind_t g_ws2812b_bind = LD_PAL_BIND_NONE;

void ws2812b_pal_bind(const ld_pal_bind_t *b) { if (b) g_ws2812b_bind = *b; }

uint8_t ws2812b_interface_spi_10mhz_init(void)
{
    return 0;
}

uint8_t ws2812b_interface_spi_deinit(void)
{
    return 0;
}

uint8_t ws2812b_interface_spi_write_cmd(uint8_t *buf, uint16_t len)
{
    return ld_spi_frame(g_ws2812b_bind.spi, 0, 0, buf, len, 0, 0);
}

void ws2812b_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void ws2812b_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
