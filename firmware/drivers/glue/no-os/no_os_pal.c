/**
 * @file no_os_pal.c
 * @brief no_os_pal.h 的实现（XinTai 自写，AGPL-3.0-or-later）。
 */
#include <errno.h>
#include <string.h>
#include "pal.h"
#include "no_os_pal.h"
#include "no_os_alloc.h"
#include "no_os_delay.h"

#define PAL_SPI_MAX 64u

static int32_t e(dz_err_t r) { return r == DZ_OK ? 0 : -EIO; }

/* ---------------- SPI ---------------- */
static int32_t pal_spi_init(struct no_os_spi_desc **d, const struct no_os_spi_init_param *p)
{
    struct no_os_spi_desc *x;
    if (!d || !p) return -EINVAL;
    x = no_os_calloc(1, sizeof *x);
    if (!x) return -ENOMEM;
    x->device_id = p->device_id; x->max_speed_hz = p->max_speed_hz; x->chip_select = p->chip_select;
    x->mode = p->mode; x->bit_order = p->bit_order; x->extra = p->extra;
    *d = x;
    return 0;
}

static int32_t pal_spi_wr(struct no_os_spi_desc *d, uint8_t *data, uint16_t n)
{
    if (!d || !data || n > PAL_SPI_MAX) return -EINVAL;
    return e(pal_spi_xfer((pal_id_t)d->device_id, data, data, n));
}

/* 连续 cs_change=0 的消息并成一个片选窗口发出。 */
static int32_t pal_spi_transfer(struct no_os_spi_desc *d, struct no_os_spi_msg *m, uint32_t k)
{
    uint8_t tx[PAL_SPI_MAX], rx[PAL_SPI_MAX];
    uint32_t i = 0;
    if (!d || (!m && k)) return -EINVAL;
    while (i < k) {
        uint32_t j = i, n = 0, off = 0;
        for (;;) { n += m[j].bytes_number; if (m[j].cs_change || j + 1 == k) break; j++; }
        if (n > PAL_SPI_MAX) return -EINVAL;
        for (uint32_t q = i; q <= j; q++) {
            if (m[q].tx_buff) memcpy(tx + off, m[q].tx_buff, m[q].bytes_number); else memset(tx + off, 0, m[q].bytes_number);
            off += m[q].bytes_number;
        }
        if (n && pal_spi_xfer((pal_id_t)d->device_id, tx, rx, (uint16_t)n) != DZ_OK) return -EIO;
        off = 0;
        for (uint32_t q = i; q <= j; q++) {
            if (m[q].rx_buff) memcpy(m[q].rx_buff, rx + off, m[q].bytes_number);
            off += m[q].bytes_number;
            if (m[q].cs_change_delay) pal_delay_us(m[q].cs_change_delay);
        }
        i = j + 1;
    }
    return 0;
}

static int32_t pal_spi_remove(struct no_os_spi_desc *d) { no_os_free(d); return 0; }

const struct no_os_spi_platform_ops pal_spi_ops = {
    .init = pal_spi_init, .write_and_read = pal_spi_wr, .transfer = pal_spi_transfer, .remove = pal_spi_remove,
};

/* ---------------- I2C ---------------- */
typedef struct { int pending; uint8_t reg; } pal_i2c_state_t;

static int32_t pal_i2c_init(struct no_os_i2c_desc **d, const struct no_os_i2c_init_param *p)
{
    struct no_os_i2c_desc *x;
    if (!d || !p) return -EINVAL;
    x = no_os_calloc(1, sizeof *x);
    if (!x) return -ENOMEM;
    x->device_id = p->device_id; x->max_speed_hz = p->max_speed_hz; x->slave_address = p->slave_address;
    x->extra = no_os_calloc(1, sizeof(pal_i2c_state_t));
    if (!x->extra) { no_os_free(x); return -ENOMEM; }
    *d = x;
    return 0;
}

static int32_t pal_i2c_write(struct no_os_i2c_desc *d, uint8_t *data, uint8_t n, uint8_t stop)
{
    pal_i2c_state_t *s;
    if (!d || !data || n == 0u) return -EINVAL;
    s = d->extra;
    if (!stop && n == 1u) { s->pending = 1; s->reg = data[0]; return 0; }   /* 寄存器指针，等后面的读 */
    s->pending = 0;
    return e(pal_i2c_mem_write((pal_id_t)d->device_id, d->slave_address, data[0], data + 1, (uint16_t)(n - 1u)));
}

static int32_t pal_i2c_read(struct no_os_i2c_desc *d, uint8_t *data, uint8_t n, uint8_t stop)
{
    pal_i2c_state_t *s;
    (void)stop;
    if (!d || !data) return -EINVAL;
    s = d->extra;
    if (!s->pending) return -ENOSYS;   /* pal 1.1 没有无寄存器的纯读 */
    s->pending = 0;
    return e(pal_i2c_mem_read((pal_id_t)d->device_id, d->slave_address, s->reg, data, n));
}

static int32_t pal_i2c_remove(struct no_os_i2c_desc *d) { if (d) no_os_free(d->extra); no_os_free(d); return 0; }

const struct no_os_i2c_platform_ops pal_i2c_ops = {
    .i2c_ops_init = pal_i2c_init, .i2c_ops_write = pal_i2c_write, .i2c_ops_read = pal_i2c_read, .i2c_ops_remove = pal_i2c_remove,
};

/* ---------------- GPIO ---------------- */
static int32_t pal_gpio_get(struct no_os_gpio_desc **d, const struct no_os_gpio_init_param *p)
{
    struct no_os_gpio_desc *x;
    if (!d || !p) return -EINVAL;
    x = no_os_calloc(1, sizeof *x);
    if (!x) return -ENOMEM;
    x->port = p->port; x->number = p->number; x->pull = p->pull; x->extra = p->extra;
    *d = x;
    return 0;
}

static int32_t pal_gpio_get_opt(struct no_os_gpio_desc **d, const struct no_os_gpio_init_param *p)
{
    if (!p) { if (d) *d = NULL; return 0; }
    return pal_gpio_get(d, p);
}

static int32_t pal_gpio_remove(struct no_os_gpio_desc *d) { no_os_free(d); return 0; }
static int32_t pal_gpio_in(struct no_os_gpio_desc *d) { return d ? 0 : -EINVAL; }   /* 方向由 board.yaml 决定 */
static int32_t pal_gpio_set(struct no_os_gpio_desc *d, uint8_t v) { return d ? e(pal_gpio_write((pal_id_t)d->number, v != 0u)) : -EINVAL; }
static int32_t pal_gpio_out(struct no_os_gpio_desc *d, uint8_t v) { return pal_gpio_set(d, v); }
static int32_t pal_gpio_dir(struct no_os_gpio_desc *d, uint8_t *dir) { (void)d; (void)dir; return -ENOSYS; }
static int32_t pal_gpio_val(struct no_os_gpio_desc *d, uint8_t *v)
{
    bool b = false;
    if (!d || !v) return -EINVAL;
    if (pal_gpio_read((pal_id_t)d->number, &b) != DZ_OK) return -EIO;
    *v = b ? 1u : 0u;
    return 0;
}

const struct no_os_gpio_platform_ops pal_gpio_ops = {
    .gpio_ops_get = pal_gpio_get, .gpio_ops_get_optional = pal_gpio_get_opt, .gpio_ops_remove = pal_gpio_remove,
    .gpio_ops_direction_input = pal_gpio_in, .gpio_ops_direction_output = pal_gpio_out,
    .gpio_ops_get_direction = pal_gpio_dir, .gpio_ops_set_value = pal_gpio_set, .gpio_ops_get_value = pal_gpio_val,
};

/* ---------------- UART ---------------- */
static int32_t pal_uart_init_(struct no_os_uart_desc **d, const struct no_os_uart_init_param *p)
{
    struct no_os_uart_desc *x;
    if (!d || !p) return -EINVAL;
    x = no_os_calloc(1, sizeof *x);
    if (!x) return -ENOMEM;
    x->device_id = p->device_id; x->baud_rate = p->baud_rate; x->extra = p->extra;
    *d = x;
    return 0;
}

static int32_t pal_uart_rd(struct no_os_uart_desc *d, uint8_t *b, uint32_t n)
{
    uint16_t got = 0;
    if (!d || !b) return -EINVAL;
    if (pal_uart_read(d->device_id, b, (uint16_t)(n > 0xFFFFu ? 0xFFFFu : n), &got) != DZ_OK) return -EIO;
    return got;
}

static int32_t pal_uart_wr(struct no_os_uart_desc *d, const uint8_t *b, uint32_t n)
{
    if (!d || !b || n > 0xFFFFu) return -EINVAL;
    return pal_uart_write(d->device_id, b, (uint16_t)n) == DZ_OK ? (int32_t)n : -EIO;
}

static int32_t pal_uart_rm(struct no_os_uart_desc *d) { no_os_free(d); return 0; }
static uint32_t pal_uart_err(struct no_os_uart_desc *d) { uint32_t x = 0; if (d) (void)pal_uart_rx_dropped(d->device_id, &x); return x; }

const struct no_os_uart_platform_ops pal_uart_ops = {
    .init = pal_uart_init_, .read = pal_uart_rd, .write = pal_uart_wr,
    .read_nonblocking = pal_uart_rd, .write_nonblocking = pal_uart_wr, .remove = pal_uart_rm, .get_errors = pal_uart_err,
};

/* ---------------- delay ---------------- */
void no_os_udelay(uint32_t usecs) { pal_delay_us(usecs); }
void no_os_mdelay(uint32_t msecs) { pal_delay_ms(msecs); }
struct no_os_time no_os_get_time(void)
{
    uint32_t us = pal_micros();
    struct no_os_time t = { us / 1000000u, us % 1000000u };
    return t;
}
