/**
 * @file ld_pal.c
 * @brief ld_pal.h 的实现（XinTai 自写，AGPL-3.0-or-later）。
 */
#include "ld_pal.h"
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#define LD_SPI_MAX 64u

static uint8_t ok(dz_err_t e) { return e == DZ_OK ? 0u : 1u; }

uint8_t ld_iic_read(pal_id_t id, uint8_t addr8, uint8_t reg, uint8_t *buf, uint16_t len)
{
    return ok(pal_i2c_mem_read(id, (uint8_t)(addr8 >> 1), reg, buf, len));
}

uint8_t ld_iic_write(pal_id_t id, uint8_t addr8, uint8_t reg, const uint8_t *buf, uint16_t len)
{
    return ok(pal_i2c_mem_write(id, (uint8_t)(addr8 >> 1), reg, buf, len));
}

/* START addr+W b0 b1..bn STOP 与 mem_write(reg=b0, b1..bn) 在线上逐位相同。 */
uint8_t ld_iic_write_cmd(pal_id_t id, uint8_t addr8, const uint8_t *buf, uint16_t len)
{
    if (!buf || len == 0u) return 1u;
    return ok(pal_i2c_mem_write(id, (uint8_t)(addr8 >> 1), buf[0], buf + 1, (uint16_t)(len - 1u)));
}

uint8_t ld_iic_read_cmd(pal_id_t id, uint8_t addr8, uint8_t *buf, uint16_t len)
{
    (void)id; (void)addr8; (void)buf; (void)len;
    return 1u;   /* pal 1.1 没有无寄存器的纯读；见 ld_pal.h 限制 */
}

uint8_t ld_iic_write16(pal_id_t id, uint8_t addr8, uint16_t reg, const uint8_t *buf, uint16_t len)
{
    uint8_t tmp[33];
    if (len > 31u || (len && !buf)) return 1u;
    tmp[0] = (uint8_t)(reg & 0xFFu);
    if (len) memcpy(tmp + 1, buf, len);
    return ok(pal_i2c_mem_write(id, (uint8_t)(addr8 >> 1), (uint8_t)(reg >> 8), tmp, (uint16_t)(len + 1u)));
}

uint8_t ld_iic_read16(pal_id_t id, uint8_t addr8, uint16_t reg, uint8_t *buf, uint16_t len)
{
    (void)id; (void)addr8; (void)reg; (void)buf; (void)len;
    return 1u;   /* pal 1.1 没有 16 位寄存器地址的读 */
}

uint8_t ld_spi_frame(pal_id_t id, const uint8_t *hdr, uint16_t hn, const uint8_t *tx, uint16_t tn, uint8_t *rx, uint16_t rn)
{
    uint8_t t[LD_SPI_MAX], r[LD_SPI_MAX];
    uint32_t n = (uint32_t)hn + tn + rn;
    if (n == 0u || n > LD_SPI_MAX) return 1u;
    memset(t, 0xFF, sizeof t);
    if (hn) memcpy(t, hdr, hn);
    if (tn) memcpy(t + hn, tx, tn);
    if (pal_spi_xfer(id, t, rn ? r : NULL, (uint16_t)n) != DZ_OK) return 1u;
    if (rn) memcpy(rx, r + hn + tn, rn);
    return 0u;
}

uint8_t ld_spi_transmit(pal_id_t id, const uint8_t *tx, uint8_t *rx, uint16_t len)
{
    if (len > LD_SPI_MAX) return 1u;
    return ok(pal_spi_xfer(id, tx, rx, len));
}

uint8_t ld_uart_write(pal_id_t id, const uint8_t *buf, uint16_t len) { return ok(pal_uart_write(id, buf, len)); }

uint16_t ld_uart_read(pal_id_t id, uint8_t *buf, uint16_t len)
{
    uint16_t got = 0;
    if (pal_uart_read(id, buf, len, &got) != DZ_OK) return 0;
    return got;
}

uint8_t ld_uart_flush(pal_id_t id)
{
    uint8_t junk[32]; uint16_t got;
    do { got = 0; if (pal_uart_read(id, junk, sizeof junk, &got) != DZ_OK) return 1u; } while (got);
    return 0u;
}

uint8_t ld_adc_read(pal_id_t id, uint16_t *raw) { return ok(pal_adc_read(id, raw)); }

uint8_t ld_gpio_write(pal_id_t id, uint8_t level) { return ok(pal_gpio_write(id, level != 0u)); }

uint8_t ld_gpio_read(pal_id_t id, uint8_t *level)
{
    bool v = false;
    if (!level || pal_gpio_read(id, &v) != DZ_OK) return 1u;
    *level = v ? 1u : 0u;
    return 0u;
}

void ld_delay_ms(uint32_t ms) { pal_delay_ms(ms); }
void ld_delay_us(uint32_t us) { pal_delay_us(us); }

__attribute__((weak)) void ld_pal_debug_sink(const char *line, uint16_t len) { (void)line; (void)len; }

void ld_debug_vprint(const char *fmt, __builtin_va_list ap)
{
    char buf[128];
    int n = vsnprintf(buf, sizeof buf, fmt, ap);
    if (n > 0) ld_pal_debug_sink(buf, (uint16_t)(n < (int)sizeof buf ? n : (int)sizeof buf - 1));
}

static uint32_t g_irq;
void ld_irq_disable(void) { g_irq = pal_irq_save(); }
void ld_irq_enable(void) { pal_irq_restore(g_irq); }

void ld_time_now(uint64_t *s, uint32_t *us, uint64_t *total_us, uint32_t *total_ms)
{
    uint32_t m = pal_micros();
    if (s) *s = m / 1000000u;
    if (us) *us = m % 1000000u;
    if (total_us) *total_us = m;
    if (total_ms) *total_ms = pal_millis();
}
