#include "st77xx.h"

#define CHUNK 64u

st77xx_cfg_t st77xx_cfg_st7735_128x160(pal_id_t spi, pal_id_t dc, pal_id_t rst, pal_id_t bl)
{
    st77xx_cfg_t c = { spi, dc, rst, bl, 128u, 160u, 2u, 1u, 0u, false, false };
    return c;
}
st77xx_cfg_t st77xx_cfg_st7789_240x240(pal_id_t spi, pal_id_t dc, pal_id_t rst, pal_id_t bl)
{
    st77xx_cfg_t c = { spi, dc, rst, bl, 240u, 240u, 0u, 0u, 0u, false, true };
    return c;
}

uint8_t st77xx_madctl(uint8_t rot, bool bgr)
{
    static const uint8_t m[4] = { 0x00u, 0x60u, 0xC0u, 0xA0u };   /* MY MX MV 组合 */
    return (uint8_t)(m[rot & 3u] | (bgr ? 0x08u : 0x00u));
}

static dz_err_t cmd(st77xx_t *d, uint8_t c, const uint8_t *p, uint16_t n)
{
    dz_err_t e = pal_gpio_write(d->cfg.dc, false);
    if (e != DZ_OK) return e;
    if ((e = pal_spi_xfer(d->cfg.spi, &c, 0, 1u)) != DZ_OK) return e;
    if (n == 0u) return DZ_OK;
    if ((e = pal_gpio_write(d->cfg.dc, true)) != DZ_OK) return e;
    return pal_spi_xfer(d->cfg.spi, p, 0, n);
}

static void apply_rot(st77xx_t *d)
{
    const st77xx_cfg_t *c = &d->cfg;
    bool swap = (c->rotation & 1u) != 0u;
    d->w = swap ? c->height : c->width;  d->h = swap ? c->width : c->height;
    d->xo = swap ? c->y_off : c->x_off;  d->yo = swap ? c->x_off : c->y_off;
}

dz_err_t st77xx_set_rotation(st77xx_t *d, uint8_t rot)
{
    if (!d || !d->ready) return DZ_ESTATE;
    if (rot > 3u) return DZ_EINVAL;
    d->cfg.rotation = rot;
    apply_rot(d);
    uint8_t m = st77xx_madctl(rot, d->cfg.bgr);
    return cmd(d, ST77XX_MADCTL, &m, 1u);
}

dz_err_t st77xx_init(st77xx_t *d, const st77xx_cfg_t *c)
{
    if (!d || !c) return DZ_EINVAL;
    d->ready = false;
    if (c->width == 0u || c->height == 0u || c->width > 320u || c->height > 320u || c->rotation > 3u) return DZ_EINVAL;
    if (c->dc == PAL_ID_NONE) return DZ_EINVAL;
    d->cfg = *c;
    dz_err_t e;
    if (c->rst != PAL_ID_NONE) {
        if ((e = pal_gpio_write(c->rst, true)) != DZ_OK) return e;
        pal_delay_ms(1u);
        if ((e = pal_gpio_write(c->rst, false)) != DZ_OK) return e;
        pal_delay_ms(120u);
    }
    if ((e = cmd(d, ST77XX_SWRESET, 0, 0)) != DZ_OK) return e;
    pal_delay_ms(150u);
    if ((e = cmd(d, ST77XX_SLPOUT, 0, 0)) != DZ_OK) return e;
    pal_delay_ms(120u);
    const uint8_t colmod = 0x05u;
    if ((e = cmd(d, ST77XX_COLMOD, &colmod, 1u)) != DZ_OK) return e;
    d->ready = true;
    if ((e = st77xx_set_rotation(d, c->rotation)) != DZ_OK) { d->ready = false; return e; }
    if ((e = cmd(d, c->invert ? ST77XX_INVON : ST77XX_INVOFF, 0, 0)) != DZ_OK ||
        (e = cmd(d, ST77XX_NORON, 0, 0)) != DZ_OK ||
        (e = cmd(d, ST77XX_DISPON, 0, 0)) != DZ_OK) { d->ready = false; return e; }
    pal_delay_ms(10u);
    if (c->bl != PAL_ID_NONE && (e = pal_gpio_write(c->bl, true)) != DZ_OK) { d->ready = false; return e; }
    return DZ_OK;
}

static dz_err_t window(st77xx_t *d, uint16_t x, uint16_t y, uint16_t w, uint16_t h)
{
    uint16_t x0 = (uint16_t)(x + d->xo), x1 = (uint16_t)(x0 + w - 1u);
    uint16_t y0 = (uint16_t)(y + d->yo), y1 = (uint16_t)(y0 + h - 1u);
    uint8_t ca[4] = { (uint8_t)(x0 >> 8), (uint8_t)x0, (uint8_t)(x1 >> 8), (uint8_t)x1 };
    uint8_t ra[4] = { (uint8_t)(y0 >> 8), (uint8_t)y0, (uint8_t)(y1 >> 8), (uint8_t)y1 };
    dz_err_t e = cmd(d, ST77XX_CASET, ca, 4u);
    if (e == DZ_OK) e = cmd(d, ST77XX_RASET, ra, 4u);
    if (e == DZ_OK) e = cmd(d, ST77XX_RAMWR, 0, 0);
    if (e == DZ_OK) e = pal_gpio_write(d->cfg.dc, true);
    return e;
}

/* 裁剪到屏内；完全在外返回 false */
static bool clip(const st77xx_t *d, int *x, int *y, int *w, int *h)
{
    if (*w <= 0 || *h <= 0) return false;
    if (*x < 0) { *w += *x; *x = 0; }
    if (*y < 0) { *h += *y; *y = 0; }
    if (*x + *w > (int)d->w) *w = (int)d->w - *x;
    if (*y + *h > (int)d->h) *h = (int)d->h - *y;
    return *w > 0 && *h > 0;
}

dz_err_t st77xx_fill_rect(st77xx_t *d, int x, int y, int w, int h, uint16_t color)
{
    if (!d || !d->ready) return DZ_ESTATE;
    if (!clip(d, &x, &y, &w, &h)) return DZ_OK;
    dz_err_t e = window(d, (uint16_t)x, (uint16_t)y, (uint16_t)w, (uint16_t)h);
    if (e != DZ_OK) return e;
    uint8_t buf[CHUNK];
    for (unsigned i = 0; i < CHUNK; i += 2u) { buf[i] = (uint8_t)(color >> 8); buf[i + 1u] = (uint8_t)color; }
    uint32_t left = (uint32_t)w * (uint32_t)h * 2u;
    while (left) {
        uint16_t k = left > CHUNK ? (uint16_t)CHUNK : (uint16_t)left;
        if ((e = pal_spi_xfer(d->cfg.spi, buf, 0, k)) != DZ_OK) return e;
        left -= k;
    }
    return DZ_OK;
}

dz_err_t st77xx_fill(st77xx_t *d, uint16_t color)
{
    if (!d || !d->ready) return DZ_ESTATE;
    return st77xx_fill_rect(d, 0, 0, (int)d->w, (int)d->h, color);
}

dz_err_t st77xx_pixel(st77xx_t *d, int x, int y, uint16_t color) { return st77xx_fill_rect(d, x, y, 1, 1, color); }

int st77xx_text(st77xx_t *d, int x, int y, const char *s, const uint8_t (*font)[8],
                uint16_t fg, uint16_t bg, uint8_t scale)
{
    if (!d || !d->ready) return (int)DZ_ESTATE;
    if (!s || !font || scale == 0u || scale > 4u) return (int)DZ_EINVAL;
    int n = 0, cw = 8 * (int)scale;
    for (; *s; s++, x += cw) {
        if (x < 0 || y < 0 || x + cw > (int)d->w || y + cw > (int)d->h) continue;   /* 整字裁掉 */
        uint8_t ch = (uint8_t)*s;
        const uint8_t *g = font[(ch >= 0x20u && ch < 0x7Fu) ? ch - 0x20u : '?' - 0x20u];
        dz_err_t e = window(d, (uint16_t)x, (uint16_t)y, (uint16_t)cw, (uint16_t)cw);
        if (e != DZ_OK) return (int)e;
        uint8_t buf[CHUNK]; unsigned k = 0;
        for (int row = 0; row < cw; row++) {
            int r = row / (int)scale;
            for (int col = 0; col < cw; col++) {
                uint16_t px = (g[col / (int)scale] >> r) & 1u ? fg : bg;
                buf[k++] = (uint8_t)(px >> 8); buf[k++] = (uint8_t)px;
                if (k == CHUNK) { if ((e = pal_spi_xfer(d->cfg.spi, buf, 0, (uint16_t)k)) != DZ_OK) return (int)e; k = 0; }
            }
        }
        if (k && (e = pal_spi_xfer(d->cfg.spi, buf, 0, (uint16_t)k)) != DZ_OK) return (int)e;
        n++;
    }
    return n;
}

dz_err_t st77xx_backlight(st77xx_t *d, bool on)
{
    if (!d || !d->ready) return DZ_ESTATE;
    return d->cfg.bl != PAL_ID_NONE ? pal_gpio_write(d->cfg.bl, on) : DZ_ENOTSUP;
}
uint16_t st77xx_width(const st77xx_t *d) { return d ? d->w : 0u; }
uint16_t st77xx_height(const st77xx_t *d) { return d ? d->h : 0u; }

dz_err_t st77xx_selftest(void)
{
    if (st77xx_madctl(0, false) != 0x00u || st77xx_madctl(1, true) != 0x68u || st77xx_madctl(3, false) != 0xA0u) return DZ_EFAIL;
    if (ST77XX_RGB(255, 0, 0) != ST77XX_RED || ST77XX_RGB(0, 255, 0) != ST77XX_GREEN) return DZ_EFAIL;
    return DZ_OK;
}
