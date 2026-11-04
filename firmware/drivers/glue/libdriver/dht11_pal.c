/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_dht11_interface.h"
#include "dht11_pal.h"

static ld_pal_bind_t g_dht11_bind = LD_PAL_BIND_NONE;

void dht11_pal_bind(const ld_pal_bind_t *b) { if (b) g_dht11_bind = *b; }

uint8_t dht11_interface_init(void)
{
    return 0;
}

uint8_t dht11_interface_deinit(void)
{
    return 0;
}

uint8_t dht11_interface_read(uint8_t *value)
{
    return ld_gpio_read(g_dht11_bind.gpio[LD_DHT11_GPIO_DATA], value);
}

uint8_t dht11_interface_write(uint8_t value)
{
    return ld_gpio_write(g_dht11_bind.gpio[LD_DHT11_GPIO_DATA], value);
}

void dht11_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void dht11_interface_delay_us(uint32_t us)
{
    ld_delay_us(us);
}

void dht11_interface_enable_irq(void)
{
    ld_irq_enable();
}

void dht11_interface_disable_irq(void)
{
    ld_irq_disable();
}

void dht11_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
