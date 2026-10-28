#include "ssd1306.h"
#include <string.h>

static dz_err_t cmds(ssd1306_t *d, const uint8_t *c, uint16_t n) { return d->write(d->ctx, false, c, n); }

dz_err_t ssd1306_init(ssd1306_t *d, ssd1306_write_fn write, void *ctx, uint8_t height, bool flip)
{
    /* 数据手册命令：AE 关显示；D5 时钟分频；A8 复用比；D3 显示偏移；40 起始行；8D 14 开内部升压；
     * 20 00 水平寻址；A1/A0 段重映射；C8/C0 COM 扫描方向；DA COM 引脚配置；81 对比度；D9 预充电；
     * DB VCOMH；A4 跟随显存；A6 正显；AF 开显示。 */
    uint8_t seq[] = { 0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40, 0x8D, 0x14, 0x20, 0x00,
                      0xA1, 0xC8, 0xDA, 0x12, 0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF };
    if (!d || !write || (height != 64u && height != 32u)) return DZ_EINVAL;
    d->write = write; d->ctx = ctx; d->height = height; d->flip = flip;
    memset(d->buf, 0, sizeof d->buf);
    seq[4] = (uint8_t)(height - 1u);
    seq[15] = (height == 64u) ? 0x12u : 0x02u;
    if (flip) { seq[12] = 0xA0; seq[13] = 0xC0; }
    return cmds(d, seq, (uint16_t)sizeof seq);
}

dz_err_t ssd1306_flush(ssd1306_t *d)
{
    uint8_t win[6] = { 0x21, 0x00, 0x7F, 0x22, 0x00, 0x07 };
    uint16_t n, off;
    dz_err_t e;
    if (!d || !d->write) return DZ_ESTATE;
    win[5] = (uint8_t)(d->height / 8u - 1u);
    if ((e = cmds(d, win, 6u)) != DZ_OK) return e;
    n = (uint16_t)(SSD1306_W * d->height / 8u);
    for (off = 0u; off < n; off += 128u)          /* 分块，照顾 I2C 驱动的单次长度限制 */
        if ((e = d->write(d->ctx, true, &d->buf[off], 128u)) != DZ_OK) return e;
    return DZ_OK;
}

dz_err_t ssd1306_power(ssd1306_t *d, bool on)
{
    uint8_t c = on ? 0xAFu : 0xAEu;
    return (d && d->write) ? cmds(d, &c, 1u) : DZ_ESTATE;
}

dz_err_t ssd1306_contrast(ssd1306_t *d, uint8_t level)
{
    uint8_t c[2];
    c[0] = 0x81u; c[1] = level;
    return (d && d->write) ? cmds(d, c, 2u) : DZ_ESTATE;
}

void ssd1306_clear(ssd1306_t *d) { if (d) memset(d->buf, 0, sizeof d->buf); }

void ssd1306_pixel(ssd1306_t *d, int x, int y, bool on)
{
    uint8_t *p;
    if (!d || x < 0 || y < 0 || x >= (int)SSD1306_W || y >= (int)d->height) return;
    p = &d->buf[(unsigned)(y / 8) * SSD1306_W + (unsigned)x];
    if (on) *p |= (uint8_t)(1u << (y & 7)); else *p &= (uint8_t)~(1u << (y & 7));
}

bool ssd1306_get_pixel(const ssd1306_t *d, int x, int y)
{
    if (!d || x < 0 || y < 0 || x >= (int)SSD1306_W || y >= (int)d->height) return false;
    return (d->buf[(unsigned)(y / 8) * SSD1306_W + (unsigned)x] >> (y & 7)) & 1u;
}

void ssd1306_fill_rect(ssd1306_t *d, int x, int y, int w, int h, bool on)
{
    int i, j;
    for (j = y; j < y + h; j++) for (i = x; i < x + w; i++) ssd1306_pixel(d, i, j, on);
}

int ssd1306_text(ssd1306_t *d, int col, int row, const char *s)
{
    int n = 0;
    if (!d || !s || row < 0 || row >= (int)(d->height / 8u)) return 0;
    for (; *s && col < (int)(SSD1306_W / 8u); s++, col++, n++) {
        unsigned char c = (unsigned char)*s;
        if (col < 0) continue;
        if (c < 0x20u || c > 0x7Eu) c = '?';
        memcpy(&d->buf[(unsigned)row * SSD1306_W + (unsigned)col * 8u], ssd1306_font8x8[c - 0x20u], 8u);
    }
    return n;
}

int ssd1306_label_float(ssd1306_t *d, int col, int row, const char *label, float v, int decimals)
{
    char s[24];
    int i = 0, k, dec = decimals < 0 ? 0 : (decimals > 4 ? 4 : decimals);
    unsigned long scale = 1u, ip, fp;
    double a;
    while (label && *label && i < 10) s[i++] = *label++;
    if (i) s[i++] = ' ';
    if (!(v == v)) { s[i++] = 'n'; s[i++] = 'a'; s[i++] = 'n'; s[i] = 0; return ssd1306_text(d, col, row, s); }
    for (k = 0; k < dec; k++) scale *= 10u;
    if (v < 0) { s[i++] = '-'; v = -v; }
    a = (double)v * (double)scale + 0.5;
    if (a > 99999999.0) a = 99999999.0;
    ip = (unsigned long)a / scale; fp = (unsigned long)a % scale;
    { char t[12]; int m = 0; do { t[m++] = (char)('0' + ip % 10u); ip /= 10u; } while (ip && m < 11);
      while (m) s[i++] = t[--m]; }
    if (dec) { s[i++] = '.'; for (k = dec - 1; k >= 0; k--) { s[i + k] = (char)('0' + fp % 10u); fp /= 10u; } i += dec; }
    s[i] = 0;
    return ssd1306_text(d, col, row, s);
}

static uint32_t st_bytes;
static dz_err_t st_write(void *ctx, bool is_data, const uint8_t *b, uint16_t n)
{
    (void)ctx; (void)b;
    if (is_data) st_bytes += n;
    return DZ_OK;
}

dz_err_t ssd1306_selftest(void)
{
    static ssd1306_t d;
    st_bytes = 0u;
    if (ssd1306_init(&d, st_write, 0, 64u, false) != DZ_OK) return DZ_EFAIL;
    ssd1306_pixel(&d, 127, 63, true);
    if (!ssd1306_get_pixel(&d, 127, 63) || d.buf[1023] != 0x80u) return DZ_EFAIL;
    ssd1306_pixel(&d, 128, 0, true);                       /* 越界忽略 */
    if (ssd1306_flush(&d) != DZ_OK || st_bytes != 1024u) return DZ_EFAIL;
    return ssd1306_text(&d, 15, 0, "AB") == 1 ? DZ_OK : DZ_EFAIL;
}
