/**
 * @file ssd1306.h
 * @brief SSD1306 OLED（128×64 / 128×32）帧缓冲驱动，传输层用回调；1.1.0 起自带 PAL I2C / PAL SPI 两种现成传输（ssd1306_tr_i2c / ssd1306_tr_spi）。
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
#include "pal.h"
#define SSD1306_VERSION "1.1.0"
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
/* ---- 现成传输（1.1.0） ---- */
/** I2C 传输上下文：控制字节 0x00/0x40 作为 pal_i2c_mem_write 的 reg 发出，数据按 16 字节分块。 */
typedef struct { pal_id_t i2c; uint8_t addr7; } ssd1306_i2c_t;   /**< addr7 常见 0x3C（SA0=0）或 0x3D */
dz_err_t ssd1306_tr_i2c(void *ctx, bool is_data, const uint8_t *buf, uint16_t n);
/** SPI 传输上下文（4 线 SPI：SCK/MOSI/CS 由 board.yaml spi 资源管，D/C 与 RES 是 GPIO）。rst 可为 PAL_ID_NONE。 */
typedef struct { pal_id_t spi; pal_id_t dc; pal_id_t rst; } ssd1306_spi_t;
dz_err_t ssd1306_tr_spi(void *ctx, bool is_data, const uint8_t *buf, uint16_t n);
/** SPI 屏硬复位（RES 拉有效 ≥3 us 再释放；board.yaml 里 rst 配 active_low）。阻塞约 1 ms，只在初始化时用。 */
dz_err_t ssd1306_spi_reset(const ssd1306_spi_t *t);
dz_err_t ssd1306_selftest(void);
#endif
