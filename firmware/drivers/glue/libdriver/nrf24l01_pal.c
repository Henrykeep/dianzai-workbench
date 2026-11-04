/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_nrf24l01_interface.h"
#include "nrf24l01_pal.h"

static ld_pal_bind_t g_nrf24l01_bind = LD_PAL_BIND_NONE;

void nrf24l01_pal_bind(const ld_pal_bind_t *b) { if (b) g_nrf24l01_bind = *b; }

uint8_t nrf24l01_interface_spi_init(void)
{
    return 0;
}

uint8_t nrf24l01_interface_spi_deinit(void)
{
    return 0;
}

uint8_t nrf24l01_interface_spi_read(uint8_t reg, uint8_t *buf, uint16_t len)
{
    uint8_t h = (uint8_t)reg;
    return ld_spi_frame(g_nrf24l01_bind.spi, &h, 1, 0, 0, buf, len);
}

uint8_t nrf24l01_interface_spi_write(uint8_t reg, uint8_t *buf, uint16_t len)
{
    uint8_t h = (uint8_t)reg;
    return ld_spi_frame(g_nrf24l01_bind.spi, &h, 1, buf, len, 0, 0);
}

uint8_t nrf24l01_interface_gpio_init(void)
{
    return 0;
}

uint8_t nrf24l01_interface_gpio_deinit(void)
{
    return 0;
}

uint8_t nrf24l01_interface_gpio_write(uint8_t data)
{
    return ld_gpio_write(g_nrf24l01_bind.gpio[LD_NRF24L01_GPIO_GPIO], data);
}

void nrf24l01_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void nrf24l01_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}

__attribute__((weak)) void nrf24l01_interface_receive_callback(uint8_t type, uint8_t num, uint8_t *buf, uint8_t len)
{
    (void)type;
    (void)num;
    (void)buf;
    (void)len;
}
