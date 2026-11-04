/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_sht30_interface.h"
#include "sht30_pal.h"

static ld_pal_bind_t g_sht30_bind = LD_PAL_BIND_NONE;

void sht30_pal_bind(const ld_pal_bind_t *b) { if (b) g_sht30_bind = *b; }

uint8_t sht30_interface_iic_init(void)
{
    return 0;
}

uint8_t sht30_interface_iic_deinit(void)
{
    return 0;
}

uint8_t sht30_interface_iic_write_address16(uint8_t addr, uint16_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_write16(g_sht30_bind.i2c, addr, reg, buf, len);
}

uint8_t sht30_interface_iic_read_address16(uint8_t addr, uint16_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_read16(g_sht30_bind.i2c, addr, reg, buf, len);
}

uint8_t sht30_interface_iic_scl_read_address16(uint8_t addr, uint16_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_read16(g_sht30_bind.i2c, addr, reg, buf, len);
}

void sht30_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void sht30_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}

__attribute__((weak)) void sht30_interface_receive_callback(uint16_t type)
{
    (void)type;
}
