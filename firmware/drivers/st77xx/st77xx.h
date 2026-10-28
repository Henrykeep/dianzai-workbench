/**
 * @file st77xx.h
 * @brief ST7735 / ST7789 彩色 TFT（RGB565，4 线 SPI + D/C + RES + 背光），无帧缓冲：直接开窗写 GRAM。
 *
 * 只依赖 pal.h（pal_spi_xfer + pal_gpio）。字体由调用者传入（列优先、bit0 在上的 8×8 ASCII 表，
 * 例如 ssd1306_font8x8），本驱动不依赖 ssd1306 模块。
 * 初始化：SWRESET → 150 ms → SLPOUT → 120 ms → COLMOD(0x05=16bit) → MADCTL(旋转/BGR) → INVON/OFF → NORON → DISPON。
 * 命令码按 Sitronix《ST7735S Datasheet V1.1》§10.1 与《ST7789VW Datasheet V1.0》§9.1，二者这几条一致。
 * 版本：ST77XX_VERSION
 */
#ifndef ST77XX_H
#define ST77XX_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "pal.h"
#define ST77XX_VERSION "1.0.0"

#define ST77XX_SWRESET 0x01u
#define ST77XX_SLPOUT  0x11u
#define ST77XX_NORON   0x13u
#define ST77XX_INVOFF  0x20u
#define ST77XX_INVON   0x21u
#define ST77XX_DISPOFF 0x28u
#define ST77XX_DISPON  0x29u
#define ST77XX_CASET   0x2Au
#define ST77XX_RASET   0x2Bu
#define ST77XX_RAMWR   0x2Cu
#define ST77XX_MADCTL  0x36u
#define ST77XX_COLMOD  0x3Au

#define ST77XX_RGB(r, g, b) ((uint16_t)((((r) & 0xF8u) << 8) | (((g) & 0xFCu) << 3) | ((b) >> 3)))
#define ST77XX_BLACK 0x0000u
#define ST77XX_WHITE 0xFFFFu
#define ST77XX_RED   0xF800u
#define ST77XX_GREEN 0x07E0u
#define ST77XX_BLUE  0x001Fu

typedef struct {
    pal_id_t spi, dc, rst, bl;   /**< rst/bl 可为 PAL_ID_NONE */
    uint16_t width, height;      /**< 旋转 0 时的物理尺寸：1.8" ST7735 128×160，1.3" ST7789 240×240，2.0" 240×320 */
    uint8_t  x_off, y_off;       /**< GRAM 偏移（旋转 0）：ST7735 绿标常见 2/1，1.3" ST7789 240×240 常见 0/80（旋转 2） */
    uint8_t  rotation;           /**< 0..3，每级 90° */
    bool     bgr;                /**< 红蓝颠倒就置 true */
    bool     invert;             /**< ST7789 IPS 屏大多需要 true */
} st77xx_cfg_t;

typedef struct {
    st77xx_cfg_t cfg;
    uint16_t w, h, xo, yo;       /**< 当前旋转下的尺寸/偏移 */
    bool ready;
} st77xx_t;

st77xx_cfg_t st77xx_cfg_st7735_128x160(pal_id_t spi, pal_id_t dc, pal_id_t rst, pal_id_t bl);
st77xx_cfg_t st77xx_cfg_st7789_240x240(pal_id_t spi, pal_id_t dc, pal_id_t rst, pal_id_t bl);
/** 初始化（阻塞约 300 ms，只在启动时调）。 */
dz_err_t st77xx_init(st77xx_t *d, const st77xx_cfg_t *cfg);
dz_err_t st77xx_set_rotation(st77xx_t *d, uint8_t rot);
/** MADCTL 值（纯函数）。 */
uint8_t st77xx_madctl(uint8_t rot, bool bgr);
dz_err_t st77xx_fill_rect(st77xx_t *d, int x, int y, int w, int h, uint16_t color);
dz_err_t st77xx_fill(st77xx_t *d, uint16_t color);
dz_err_t st77xx_pixel(st77xx_t *d, int x, int y, uint16_t color);
/** 8×8 文字（scale=1..4 放大），越界字符裁掉。返回写入字符数，出错 <0。 */
int st77xx_text(st77xx_t *d, int x, int y, const char *s, const uint8_t (*font)[8],
                uint16_t fg, uint16_t bg, uint8_t scale);
dz_err_t st77xx_backlight(st77xx_t *d, bool on);
uint16_t st77xx_width(const st77xx_t *d);
uint16_t st77xx_height(const st77xx_t *d);
dz_err_t st77xx_selftest(void);
#endif
