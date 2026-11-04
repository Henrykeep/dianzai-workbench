/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_hlw8032_interface.h"
#include "hlw8032_pal.h"

static ld_pal_bind_t g_hlw8032_bind = LD_PAL_BIND_NONE;

void hlw8032_pal_bind(const ld_pal_bind_t *b) { if (b) g_hlw8032_bind = *b; }

uint8_t hlw8032_interface_uart_init(void)
{
    return 0;
}

uint8_t hlw8032_interface_uart_deinit(void)
{
    return 0;
}

uint16_t hlw8032_interface_uart_read(uint8_t *buf, uint16_t len)
{
    return ld_uart_read(g_hlw8032_bind.uart, buf, len);
}

uint8_t hlw8032_interface_uart_flush(void)
{
    return ld_uart_flush(g_hlw8032_bind.uart);
}

void hlw8032_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void hlw8032_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
