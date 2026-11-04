/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_ads1115_interface.h"
#include "ads1115_pal.h"

static ld_pal_bind_t g_ads1115_bind = LD_PAL_BIND_NONE;

void ads1115_pal_bind(const ld_pal_bind_t *b) { if (b) g_ads1115_bind = *b; }

uint8_t ads1115_interface_iic_init(void)
{
    return 0;
}

uint8_t ads1115_interface_iic_deinit(void)
{
    return 0;
}

uint8_t ads1115_interface_iic_read(uint8_t addr, uint8_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_read(g_ads1115_bind.i2c, addr, reg, buf, len);
}

uint8_t ads1115_interface_iic_write(uint8_t addr, uint8_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_write(g_ads1115_bind.i2c, addr, reg, buf, len);
}

void ads1115_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void ads1115_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
