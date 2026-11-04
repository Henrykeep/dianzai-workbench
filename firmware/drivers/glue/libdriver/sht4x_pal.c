/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_sht4x_interface.h"
#include "sht4x_pal.h"

static ld_pal_bind_t g_sht4x_bind = LD_PAL_BIND_NONE;

void sht4x_pal_bind(const ld_pal_bind_t *b) { if (b) g_sht4x_bind = *b; }

uint8_t sht4x_interface_iic_init(void)
{
    return 0;
}

uint8_t sht4x_interface_iic_deinit(void)
{
    return 0;
}

uint8_t sht4x_interface_iic_write_cmd(uint8_t addr, uint8_t *buf, uint16_t len)
{
    return ld_iic_write_cmd(g_sht4x_bind.i2c, addr, buf, len);
}

uint8_t sht4x_interface_iic_read_cmd(uint8_t addr, uint8_t *buf, uint16_t len)
{
    return ld_iic_read_cmd(g_sht4x_bind.i2c, addr, buf, len);
}

void sht4x_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void sht4x_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
