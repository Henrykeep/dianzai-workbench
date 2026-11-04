/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_tm1637_interface.h"
#include "tm1637_pal.h"

static ld_pal_bind_t g_tm1637_bind = LD_PAL_BIND_NONE;

void tm1637_pal_bind(const ld_pal_bind_t *b) { if (b) g_tm1637_bind = *b; }

uint8_t tm1637_interface_iic_init(void)
{
    return 0;
}

uint8_t tm1637_interface_iic_deinit(void)
{
    return 0;
}

uint8_t tm1637_interface_iic_write_cmd_custom(uint8_t addr, uint8_t *buf, uint16_t len)
{
    (void)addr;
    (void)buf;
    (void)len;
    return 1;   /* 未映射：见 glue_report.json */
}

uint8_t tm1637_interface_iic_read_cmd_custom(uint8_t addr, uint8_t *buf, uint16_t len)
{
    (void)addr;
    (void)buf;
    (void)len;
    return 1;   /* 未映射：见 glue_report.json */
}

void tm1637_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void tm1637_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
