/* SSD1306 现成传输：PAL I2C / PAL SPI。命令/数据区分见 SSD1306 Datasheet §8.1.5（I2C 控制字节）与 §8.1.3（4 线 SPI D/C#）。 */
#include "ssd1306.h"

#define I2C_CHUNK 16u
#define SPI_CHUNK 64u

dz_err_t ssd1306_tr_i2c(void *ctx, bool is_data, const uint8_t *buf, uint16_t n)
{
    const ssd1306_i2c_t *t = (const ssd1306_i2c_t *)ctx;
    if (!t || !buf || n == 0u || t->addr7 > 0x7Fu) return DZ_EINVAL;
    uint8_t ctrl = is_data ? 0x40u : 0x00u;
    for (uint16_t off = 0; off < n; ) {
        uint16_t k = (uint16_t)(n - off) > I2C_CHUNK ? (uint16_t)I2C_CHUNK : (uint16_t)(n - off);
        dz_err_t e = pal_i2c_mem_write(t->i2c, t->addr7, ctrl, &buf[off], k);
        if (e != DZ_OK) return e;
        off = (uint16_t)(off + k);
    }
    return DZ_OK;
}

dz_err_t ssd1306_tr_spi(void *ctx, bool is_data, const uint8_t *buf, uint16_t n)
{
    const ssd1306_spi_t *t = (const ssd1306_spi_t *)ctx;
    if (!t || !buf || n == 0u) return DZ_EINVAL;
    dz_err_t e = pal_gpio_write(t->dc, is_data);
    if (e != DZ_OK) return e;
    for (uint16_t off = 0; off < n; ) {
        uint16_t k = (uint16_t)(n - off) > SPI_CHUNK ? (uint16_t)SPI_CHUNK : (uint16_t)(n - off);
        if ((e = pal_spi_xfer(t->spi, &buf[off], 0, k)) != DZ_OK) return e;
        off = (uint16_t)(off + k);
    }
    return DZ_OK;
}

dz_err_t ssd1306_spi_reset(const ssd1306_spi_t *t)
{
    if (!t) return DZ_EINVAL;
    if (t->rst == PAL_ID_NONE) return DZ_OK;
    dz_err_t e = pal_gpio_write(t->rst, true);
    if (e != DZ_OK) return e;
    pal_delay_us(10u);
    if ((e = pal_gpio_write(t->rst, false)) != DZ_OK) return e;
    pal_delay_ms(1u);
    return DZ_OK;
}
