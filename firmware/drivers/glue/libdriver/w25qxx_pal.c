/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_w25qxx_interface.h"
#include "w25qxx_pal.h"

static ld_pal_bind_t g_w25qxx_bind = LD_PAL_BIND_NONE;

void w25qxx_pal_bind(const ld_pal_bind_t *b) { if (b) g_w25qxx_bind = *b; }

uint8_t w25qxx_interface_spi_qspi_init(void)
{
    return 0;
}

uint8_t w25qxx_interface_spi_qspi_deinit(void)
{
    return 0;
}

uint8_t w25qxx_interface_spi_qspi_write_read(uint8_t instruction, uint8_t instruction_line, uint32_t address, uint8_t address_line, uint8_t address_len, uint32_t alternate, uint8_t alternate_line, uint8_t alternate_len, uint8_t dummy, uint8_t *in_buf, uint32_t in_len, uint8_t *out_buf, uint32_t out_len, uint8_t data_line)
{
    uint8_t h[12]; uint16_t k = 0; uint8_t i;
    if ((instruction_line > 1u) || (address_len && address_line > 1u) || (alternate_len && alternate_line > 1u) || data_line > 1u || address_len > 4u || alternate_len > 4u || (dummy % 8u)) return 1;
    if (instruction_line) h[k++] = instruction;
    for (i = 0; i < address_len; i++) h[k++] = (uint8_t)(address >> (8u * (address_len - 1u - i)));
    for (i = 0; i < alternate_len; i++) h[k++] = (uint8_t)(alternate >> (8u * (alternate_len - 1u - i)));
    for (i = 0; i < dummy / 8u && k < sizeof h; i++) h[k++] = 0xFF;
    if (in_len > 64u || out_len > 64u) return 1;
    return ld_spi_frame(g_w25qxx_bind.spi, h, k, in_buf, (uint16_t)in_len, out_buf, (uint16_t)out_len);
}

void w25qxx_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void w25qxx_interface_delay_us(uint32_t us)
{
    ld_delay_us(us);
}

void w25qxx_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
