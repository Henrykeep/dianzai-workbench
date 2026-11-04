/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_ntc_interface.h"
#include "ntc_pal.h"

static ld_pal_bind_t g_ntc_bind = LD_PAL_BIND_NONE;

void ntc_pal_bind(const ld_pal_bind_t *b) { if (b) g_ntc_bind = *b; }

uint8_t ntc_interface_adc_init(uint32_t *vcc_counter)
{
    return 0;
}

uint8_t ntc_interface_adc_deinit(void)
{
    return 0;
}

uint8_t ntc_interface_adc_read(uint32_t *counter, uint16_t len)
{
    uint16_t i, v;
    if (!counter) return 1;
    for (i = 0; i < len; i++) { if (ld_adc_read(g_ntc_bind.adc, &v)) return 1; counter[i] = v; }
    return 0;
}

void ntc_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void ntc_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
