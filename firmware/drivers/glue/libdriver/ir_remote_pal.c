/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_ir_remote_interface.h"
#include "ir_remote_pal.h"

static ld_pal_bind_t g_ir_remote_bind = LD_PAL_BIND_NONE;

void ir_remote_pal_bind(const ld_pal_bind_t *b) { if (b) g_ir_remote_bind = *b; }

uint8_t ir_remote_interface_timestamp_read(ir_remote_time_t *t)
{
    if (!t) return 1;
    ld_time_now(&t->s, &t->us, 0, 0);
    return 0;
}

void ir_remote_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void ir_remote_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}

__attribute__((weak)) void ir_remote_interface_receive_callback(ir_remote_t *data)
{
    (void)data;
}
