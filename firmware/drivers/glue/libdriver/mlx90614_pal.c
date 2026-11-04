/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_mlx90614_interface.h"
#include "mlx90614_pal.h"

static ld_pal_bind_t g_mlx90614_bind = LD_PAL_BIND_NONE;

void mlx90614_pal_bind(const ld_pal_bind_t *b) { if (b) g_mlx90614_bind = *b; }

uint8_t mlx90614_interface_iic_init(void)
{
    return 0;
}

uint8_t mlx90614_interface_iic_deinit(void)
{
    return 0;
}

uint8_t mlx90614_interface_iic_read(uint8_t addr, uint8_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_read(g_mlx90614_bind.i2c, addr, reg, buf, len);
}

uint8_t mlx90614_interface_iic_write(uint8_t addr, uint8_t reg, uint8_t *buf, uint16_t len)
{
    return ld_iic_write(g_mlx90614_bind.i2c, addr, reg, buf, len);
}

uint8_t mlx90614_interface_scl_write(uint8_t value)
{
    return ld_gpio_write(g_mlx90614_bind.gpio[LD_MLX90614_GPIO_SCL], value);
}

uint8_t mlx90614_interface_sda_write(uint8_t value)
{
    return ld_gpio_write(g_mlx90614_bind.gpio[LD_MLX90614_GPIO_SDA], value);
}

void mlx90614_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void mlx90614_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}
