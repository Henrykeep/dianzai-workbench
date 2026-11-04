/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_multi_button_interface.h"
#include "multi_button_pal.h"

static ld_pal_bind_t g_multi_button_bind = LD_PAL_BIND_NONE;

void multi_button_pal_bind(const ld_pal_bind_t *b) { if (b) g_multi_button_bind = *b; }

uint8_t multi_button_interface_matrix_init(void)
{
    return 0;
}

uint8_t multi_button_interface_matrix_deinit(void)
{
    return 0;
}

uint8_t multi_button_interface_matrix_write_row(uint16_t num, uint8_t level)
{
    (void)num;
    (void)level;
    return 1;   /* 未映射：见 glue_report.json */
}

uint8_t multi_button_interface_matrix_read_row(uint32_t *col_array)
{
    (void)col_array;
    return 1;   /* 未映射：见 glue_report.json */
}

uint8_t multi_button_interface_timestamp_read(multi_button_time_t *t)
{
    if (!t) return 1;
    ld_time_now(&t->s, &t->us, 0, 0);
    return 0;
}

void multi_button_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void multi_button_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}

__attribute__((weak)) void multi_button_interface_receive_callback(uint16_t row, uint16_t col, multi_button_t *data)
{
    (void)row;
    (void)col;
    (void)data;
}
