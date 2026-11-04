/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_x9cxx_interface.h"
#include "x9cxx_pal.h"

static ld_pal_bind_t g_x9cxx_bind = LD_PAL_BIND_NONE;

void x9cxx_pal_bind(const ld_pal_bind_t *b) { if (b) g_x9cxx_bind = *b; }

uint8_t x9cxx_interface_cs_gpio_init(void)
{
    return 0;
}

uint8_t x9cxx_interface_cs_gpio_deinit(void)
{
    return 0;
}

uint8_t x9cxx_interface_cs_gpio_write(uint8_t value)
{
    return ld_gpio_write(g_x9cxx_bind.gpio[LD_X9CXX_GPIO_CS], value);
}

uint8_t x9cxx_interface_up_down_gpio_init(void)
{
    return 0;
}

uint8_t x9cxx_interface_up_down_gpio_deinit(void)
{
    return 0;
}

uint8_t x9cxx_interface_up_down_gpio_write(uint8_t value)
{
    return ld_gpio_write(g_x9cxx_bind.gpio[LD_X9CXX_GPIO_UP_DOWN], value);
}

uint8_t x9cxx_interface_inc_gpio_init(void)
{
    return 0;
}

uint8_t x9cxx_interface_inc_gpio_deinit(void)
{
    return 0;
}

uint8_t x9cxx_interface_inc_gpio_write(uint8_t value)
{
    return ld_gpio_write(g_x9cxx_bind.gpio[LD_X9CXX_GPIO_INC], value);
}

void x9cxx_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void x9cxx_interface_delay_us(uint32_t us)
{
    ld_delay_us(us);
}

void x9cxx_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
