/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_mfrc522_interface.h"
#include "mfrc522_pal.h"

static ld_pal_bind_t g_mfrc522_bind = LD_PAL_BIND_NONE;

void mfrc522_pal_bind(const ld_pal_bind_t *b) { if (b) g_mfrc522_bind = *b; }

uint8_t mfrc522_interface_reset_gpio_init(void)
{
    return 0;
}

uint8_t mfrc522_interface_reset_gpio_deinit(void)
{
    return 0;
}

uint8_t mfrc522_interface_reset_gpio_write(uint8_t value)
{
    return ld_gpio_write(g_mfrc522_bind.gpio[LD_MFRC522_GPIO_RESET], value);
}

uint8_t mfrc522_interface_iic_init(void)
{
    return 0;
}

uint8_t mfrc522_interface_iic_deinit(void)
{
    return 0;
}

uint8_t mfrc522_interface_iic_read(uint8_t addr, uint8_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_read(g_mfrc522_bind.i2c, addr, reg, buf, len);
}

uint8_t mfrc522_interface_iic_write(uint8_t addr, uint8_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_write(g_mfrc522_bind.i2c, addr, reg, buf, len);
}

uint8_t mfrc522_interface_spi_init(void)
{
    return 0;
}

uint8_t mfrc522_interface_spi_deinit(void)
{
    return 0;
}

uint8_t mfrc522_interface_spi_read(uint8_t reg, uint8_t *buf, uint16_t len)
{
    uint8_t h = (uint8_t)reg;
    return ld_spi_frame(g_mfrc522_bind.spi, &h, 1, 0, 0, buf, len);
}

uint8_t mfrc522_interface_spi_write(uint8_t reg, uint8_t *buf, uint16_t len)
{
    uint8_t h = (uint8_t)reg;
    return ld_spi_frame(g_mfrc522_bind.spi, &h, 1, buf, len, 0, 0);
}

uint8_t mfrc522_interface_uart_init(void)
{
    return 0;
}

uint8_t mfrc522_interface_uart_deinit(void)
{
    return 0;
}

uint16_t mfrc522_interface_uart_read(uint8_t *buf, uint16_t len)
{
    return ld_uart_read(g_mfrc522_bind.uart, buf, len);
}

uint8_t mfrc522_interface_uart_write(uint8_t *buf, uint16_t len)
{
    return ld_uart_write(g_mfrc522_bind.uart, buf, len);
}

uint8_t mfrc522_interface_uart_flush(void)
{
    return ld_uart_flush(g_mfrc522_bind.uart);
}

void mfrc522_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void mfrc522_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}

__attribute__((weak)) void mfrc522_interface_receive_callback(uint16_t type)
{
    (void)type;
}
