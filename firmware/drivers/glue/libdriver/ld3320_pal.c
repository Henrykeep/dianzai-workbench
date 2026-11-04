/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#include <stdint.h>
#include "driver_ld3320_interface.h"
#include "ld3320_pal.h"

static ld_pal_bind_t g_ld3320_bind = LD_PAL_BIND_NONE;

void ld3320_pal_bind(const ld_pal_bind_t *b) { if (b) g_ld3320_bind = *b; }

uint8_t ld3320_interface_spi_init(void)
{
    return 0;
}

uint8_t ld3320_interface_spi_deinit(void)
{
    return 0;
}

uint8_t ld3320_interface_spi_read_address16(uint16_t reg, uint8_t *buf, uint16_t len)
{
    uint8_t h[2] = { (uint8_t)(reg >> 8), (uint8_t)(reg & 0xFF) };
    return ld_spi_frame(g_ld3320_bind.spi, h, 2, 0, 0, buf, len);
}

uint8_t ld3320_interface_spi_write_cmd(uint8_t *buf, uint16_t len)
{
    return ld_spi_frame(g_ld3320_bind.spi, 0, 0, buf, len, 0, 0);
}

uint8_t ld3320_interface_reset_gpio_init(void)
{
    return 0;
}

uint8_t ld3320_interface_reset_gpio_deinit(void)
{
    return 0;
}

uint8_t ld3320_interface_reset_gpio_write(uint8_t data)
{
    return ld_gpio_write(g_ld3320_bind.gpio[LD_LD3320_GPIO_RESET], data);
}

void ld3320_interface_delay_ms(uint32_t ms)
{
    ld_delay_ms(ms);
}

void ld3320_interface_delay_us(uint32_t us)
{
    ld_delay_us(us);
}

void ld3320_interface_debug_print(const char *const fmt, ...)
{
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    ld_debug_vprint(fmt, ap);
    __builtin_va_end(ap);
}

uint8_t ld3320_interface_mp3_init(char *name, uint32_t *size)
{
    return 0;
}

uint8_t ld3320_interface_mp3_deinit(void)
{
    return 0;
}

uint8_t ld3320_interface_mp3_read(uint32_t addr, uint16_t size, uint8_t *buffer)
{
    (void)addr;
    (void)size;
    (void)buffer;
    return 1;   /* 未映射：见 glue_report.json */
}

__attribute__((weak)) void ld3320_interface_receive_callback(uint8_t type, uint8_t ind, char *text)
{
    (void)type;
    (void)ind;
    (void)text;
}
