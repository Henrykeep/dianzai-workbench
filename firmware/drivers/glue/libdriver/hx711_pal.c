/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_hx711_interface.h"
#include "hx711_pal.h"

static ld_pal_bind_t g_hx711_bind = LD_PAL_BIND_NONE;

void hx711_pal_bind(const ld_pal_bind_t *b) { if (b) g_hx711_bind = *b; }

uint8_t hx711_interface_bus_init(void)
{
    return 0;
}

uint8_t hx711_interface_bus_deinit(void)
{
    return 0;
}

uint8_t hx711_interface_bus_read(uint8_t *value)
{
    return ld_gpio_read(g_hx711_bind.gpio[LD_HX711_GPIO_BUS], value);
}

uint8_t hx711_interface_clock_init(void)
{
    return 0;
}

uint8_t hx711_interface_clock_deinit(void)
{
    return 0;
}

uint8_t hx711_interface_clock_write(uint8_t value)
{
    return ld_gpio_write(g_hx711_bind.gpio[LD_HX711_GPIO_CLOCK], value);
}

void hx711_interface_delay_us(uint32_t us)
{
    ld_delay_us(us);
}

void hx711_interface_enable_irq(void)
{
    ld_irq_enable();
}

void hx711_interface_disable_irq(void)
{
    ld_irq_disable();
}

void hx711_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
