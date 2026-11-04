/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_wt588e02b_interface.h"
#include "wt588e02b_pal.h"

static ld_pal_bind_t g_wt588e02b_bind = LD_PAL_BIND_NONE;

void wt588e02b_pal_bind(const ld_pal_bind_t *b) { if (b) g_wt588e02b_bind = *b; }

uint8_t wt588e02b_interface_sclk_gpio_init(void)
{
    return 0;
}

uint8_t wt588e02b_interface_sclk_gpio_deinit(void)
{
    return 0;
}

uint8_t wt588e02b_interface_sclk_gpio_write(uint8_t data)
{
    return ld_gpio_write(g_wt588e02b_bind.gpio[LD_WT588E02B_GPIO_SCLK], data);
}

uint8_t wt588e02b_interface_mosi_gpio_init(void)
{
    return 0;
}

uint8_t wt588e02b_interface_mosi_gpio_deinit(void)
{
    return 0;
}

uint8_t wt588e02b_interface_mosi_gpio_write(uint8_t data)
{
    return ld_gpio_write(g_wt588e02b_bind.gpio[LD_WT588E02B_GPIO_MOSI], data);
}

uint8_t wt588e02b_interface_miso_gpio_init(void)
{
    return 0;
}

uint8_t wt588e02b_interface_miso_gpio_deinit(void)
{
    return 0;
}

uint8_t wt588e02b_interface_miso_gpio_read(uint8_t *data)
{
    return ld_gpio_read(g_wt588e02b_bind.gpio[LD_WT588E02B_GPIO_MISO], data);
}

uint8_t wt588e02b_interface_cs_gpio_init(void)
{
    return 0;
}

uint8_t wt588e02b_interface_cs_gpio_deinit(void)
{
    return 0;
}

uint8_t wt588e02b_interface_cs_gpio_write(uint8_t data)
{
    return ld_gpio_write(g_wt588e02b_bind.gpio[LD_WT588E02B_GPIO_CS], data);
}

void wt588e02b_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void wt588e02b_interface_delay_us(uint32_t us)
{
    ld_delay_us(us);
}

uint8_t wt588e02b_interface_bin_read_init(char *name, uint32_t *size)
{
    return 0;
}

uint8_t wt588e02b_interface_bin_read(uint32_t addr, uint16_t size, uint8_t *buffer)
{
    (void)addr;
    (void)size;
    (void)buffer;
    return 1;   /* 未映射：见 glue_report.json */
}

uint8_t wt588e02b_interface_bin_read_deinit(void)
{
    return 0;
}

void wt588e02b_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
