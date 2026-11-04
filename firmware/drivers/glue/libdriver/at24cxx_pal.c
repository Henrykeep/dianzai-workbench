/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_at24cxx_interface.h"
#include "at24cxx_pal.h"

static ld_pal_bind_t g_at24cxx_bind = LD_PAL_BIND_NONE;

void at24cxx_pal_bind(const ld_pal_bind_t *b) { if (b) g_at24cxx_bind = *b; }

uint8_t at24cxx_interface_iic_init(void)
{
    return 0;
}

uint8_t at24cxx_interface_iic_deinit(void)
{
    return 0;
}

uint8_t at24cxx_interface_iic_read(uint8_t addr, uint8_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_read(g_at24cxx_bind.i2c, addr, reg, buf, len);
}

uint8_t at24cxx_interface_iic_write(uint8_t addr, uint8_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_write(g_at24cxx_bind.i2c, addr, reg, buf, len);
}

uint8_t at24cxx_interface_iic_read_address16(uint8_t addr, uint16_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_read16(g_at24cxx_bind.i2c, addr, reg, buf, len);
}

uint8_t at24cxx_interface_iic_write_address16(uint8_t addr, uint16_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_write16(g_at24cxx_bind.i2c, addr, reg, buf, len);
}

void at24cxx_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void at24cxx_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
