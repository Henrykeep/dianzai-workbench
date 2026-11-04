/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_sx1262_interface.h"
#include "sx1262_pal.h"

static ld_pal_bind_t g_sx1262_bind = LD_PAL_BIND_NONE;

void sx1262_pal_bind(const ld_pal_bind_t *b) { if (b) g_sx1262_bind = *b; }

uint8_t sx1262_interface_spi_init(void)
{
    return 0;
}

uint8_t sx1262_interface_spi_deinit(void)
{
    return 0;
}

uint8_t sx1262_interface_spi_write_read(uint8_t *in_buf, uint32_t in_len, uint8_t *out_buf, uint32_t out_len)
{
    if (in_len > 64u || out_len > 64u) return 1;
    return ld_spi_frame(g_sx1262_bind.spi, 0, 0, in_buf, (uint16_t)in_len, out_buf, (uint16_t)out_len);
}

uint8_t sx1262_interface_reset_gpio_init(void)
{
    return 0;
}

uint8_t sx1262_interface_reset_gpio_deinit(void)
{
    return 0;
}

uint8_t sx1262_interface_reset_gpio_write(uint8_t data)
{
    return ld_gpio_write(g_sx1262_bind.gpio[LD_SX1262_GPIO_RESET], data);
}

uint8_t sx1262_interface_busy_gpio_init(void)
{
    return 0;
}

uint8_t sx1262_interface_busy_gpio_deinit(void)
{
    return 0;
}

uint8_t sx1262_interface_busy_gpio_read(uint8_t *value)
{
    return ld_gpio_read(g_sx1262_bind.gpio[LD_SX1262_GPIO_BUSY], value);
}

void sx1262_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void sx1262_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}

__attribute__((weak)) void sx1262_interface_receive_callback(uint16_t type, uint8_t *buf, uint16_t len)
{
    (void)type;
    (void)buf;
    (void)len;
}
