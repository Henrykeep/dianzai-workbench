/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_ds18b20_interface.h"
#include "ds18b20_pal.h"

static ld_pal_bind_t g_ds18b20_bind = LD_PAL_BIND_NONE;

void ds18b20_pal_bind(const ld_pal_bind_t *b) { if (b) g_ds18b20_bind = *b; }

uint8_t ds18b20_interface_init(void)
{
    return 0;
}

uint8_t ds18b20_interface_deinit(void)
{
    return 0;
}

uint8_t ds18b20_interface_read(uint8_t *value)
{
    return ld_gpio_read(g_ds18b20_bind.gpio[LD_DS18B20_GPIO_DATA], value);
}

uint8_t ds18b20_interface_write(uint8_t value)
{
    return ld_gpio_write(g_ds18b20_bind.gpio[LD_DS18B20_GPIO_DATA], value);
}

void ds18b20_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void ds18b20_interface_delay_us(uint32_t us)
{
    ld_delay_us(us);
}

void ds18b20_interface_enable_irq(void)
{
    ld_irq_enable();
}

void ds18b20_interface_disable_irq(void)
{
    ld_irq_disable();
}

void ds18b20_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
