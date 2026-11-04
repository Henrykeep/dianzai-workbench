/**
 * @file oled.h
 * @brief SSD1306 128×64 单色 OLED 的帧缓冲绘图与 I2C 刷新接口。
 */
#ifndef OLED_H
#define OLED_H

#include <stdbool.h>
#include <stdint.h>

/* 本驱动固定使用 128×64 逻辑坐标，原点位于左上角。 */
#define OLED_WIDTH  (128U)
#define OLED_HEIGHT (64U)

/** SSD1306 OLED 模块的不透明实例。 */
typedef struct OLEDInstance OLEDInstance;

/* 同一实例的帧缓冲绘制与刷新应由调用者串行执行。 */

/** 注册一个使用指定 7 位 I2C 地址的 SSD1306 OLED。 */
OLEDInstance *OLEDRegister(uint8_t i2c_address);

/** 初始化 128×64 SSD1306，并清空屏幕；失败时返回 false。 */
bool OLEDInitialize(OLEDInstance *instance);

/** 用全灭或全亮像素填充本地帧缓冲区，不会立即刷新硬件。 */
bool OLEDClear(OLEDInstance *instance, bool pixels_on);

/** 设置或清除一个像素，只修改本地帧缓冲区。 */
bool OLEDSetPixel(
    OLEDInstance *instance, uint8_t x, uint8_t y, bool pixel_on);

/** 使用内置 5×7 ASCII 字体绘制一个字符。 */
bool OLEDDrawCharacter(
    OLEDInstance *instance, uint8_t x, uint8_t y, char character);

/** 使用内置 5×7 ASCII 字体绘制以 NULL 结尾的字符串。 */
bool OLEDDrawString(
    OLEDInstance *instance, uint8_t x, uint8_t y, const char *text);

/** 将完整帧缓冲区发送到 OLED。 */
bool OLEDUpdate(OLEDInstance *instance);

/** 将连续的页范围发送到 OLED；每页高度为 8 像素。 */
bool OLEDUpdatePages(
    OLEDInstance *instance, uint8_t first_page, uint8_t page_count);

/** 打开或关闭 OLED 面板显示，不清除帧缓冲区。 */
bool OLEDSetDisplayEnabled(OLEDInstance *instance, bool enabled);

/** 设置正常显示或黑白反色显示。 */
bool OLEDSetInverted(OLEDInstance *instance, bool inverted);

/** 设置 SSD1306 对比度，范围为 0x00～0xFF。 */
bool OLEDSetContrast(OLEDInstance *instance, uint8_t contrast);

#endif
