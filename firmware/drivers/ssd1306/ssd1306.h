/**
 * @file ssd1306.h
 * @brief SSD1306 OLED（128×64 / 128×32）帧缓冲驱动，传输层用回调（I2C/SPI/软件 I2C 都行，PAL 不含 I2C）。
 *
 * 所有绘图只改 RAM 中的帧缓冲（1 KB），ssd1306_flush() 一次性写屏（水平寻址模式）。
 * 初始化序列按 Solomon Systech《SSD1306 Datasheet Rev 1.1》§8–§10 的命令表与附录推荐流程编写；
 * 结构参考 Adafruit_SSD1306（BSD）与 u8g2（BSD-2）的公开做法：缓冲 + 整屏刷新 + 传输抽象。未拷贝其代码。
 * 版本：SSD1306_VERSION
 */
#ifndef SSD1306_H
#define SSD1306_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#define SSD1306_VERSION "1.0.0"
#define SSD1306_W 128u

/** 传输回调：is_data=false 发命令字节、true 发显存数据。
 *  I2C 实现：先发控制字节（命令 0x00 / 数据 0x40）再发 buf；SPI 实现：D/C 脚=is_data。返回 DZ_OK 表示成功。 */
typedef dz_err_t (*ssd1306_write_fn)(void *ctx, bool is_data, const uint8_t *buf, uint16_t n);

typedef struct {
    ssd1306_write_fn write;
    void *ctx;
    uint8_t height;             /**< 64 或 32 */
    bool flip;                  /**< 旋转 180° */
    uint8_t buf[SSD1306_W * 64u / 8u];
} ssd1306_t;

extern const uint8_t ssd1306_font8x8[95][8];

dz_err_t ssd1306_init(ssd1306_t *d, ssd1306_write_fn write, void *ctx, uint8_t height, bool flip);
dz_err_t ssd1306_flush(ssd1306_t *d);
dz_err_t ssd1306_power(ssd1306_t *d, bool on);
dz_err_t ssd1306_contrast(ssd1306_t *d, uint8_t level);
void ssd1306_clear(ssd1306_t *d);
void ssd1306_pixel(ssd1306_t *d, int x, int y, bool on);
bool ssd1306_get_pixel(const ssd1306_t *d, int x, int y);
void ssd1306_fill_rect(ssd1306_t *d, int x, int y, int w, int h, bool on);
/** 8×8 字符，col 0..15、row 0..7（以 8 像素为格）；非 ASCII 可打印字符画成 '?'。返回写入字符数。 */
int ssd1306_text(ssd1306_t *d, int col, int row, const char *s);
/** 简易格式化：标签 + 定点数，例如 ("KP", 0.72f, 3) → "KP 0.720"。返回写入字符数。 */
int ssd1306_label_float(ssd1306_t *d, int col, int row, const char *label, float v, int decimals);
dz_err_t ssd1306_selftest(void);
#endif
