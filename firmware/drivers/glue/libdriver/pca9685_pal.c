/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_pca9685_interface.h"
#include "pca9685_pal.h"

static ld_pal_bind_t g_pca9685_bind = LD_PAL_BIND_NONE;

void pca9685_pal_bind(const ld_pal_bind_t *b) { if (b) g_pca9685_bind = *b; }

uint8_t pca9685_interface_iic_init(void)
{
    return 0;
}

uint8_t pca9685_interface_iic_deinit(void)
{
    return 0;
}

uint8_t pca9685_interface_iic_read(uint8_t addr, uint8_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_read(g_pca9685_bind.i2c, addr, reg, buf, len);
}

uint8_t pca9685_interface_iic_write(uint8_t addr, uint8_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_write(g_pca9685_bind.i2c, addr, reg, buf, len);
}

uint8_t pca9685_interface_oe_init(void)
{
    return 0;
}

uint8_t pca9685_interface_oe_deinit(void)
{
    return 0;
}

uint8_t pca9685_interface_oe_write(uint8_t value)
{
    return ld_gpio_write(g_pca9685_bind.gpio[LD_PCA9685_GPIO_OE], value);
}

void pca9685_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void pca9685_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
