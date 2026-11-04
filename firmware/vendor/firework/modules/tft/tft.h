/**
 * @file tft.h
 * @brief ST7735S 初始化、逻辑画布绘制、区域刷新和面板控制接口。
 */
#ifndef TFT_H
#define TFT_H

#include <stdbool.h>
#include <stdint.h>

#include "modules/display/display.h"

#define TFT_PHYSICAL_WIDTH  (128U)
#define TFT_PHYSICAL_HEIGHT (160U)

/**
 * 当前实测的蓝色 PCB ST7735S 模块，其 128×160 可视区在控制器
 * 132×162 GRAM 中从 (2, 1) 开始。不加偏移会截掉左侧像素，并在
 * 右侧、底部留下未刷新的彩色边。其他批次若布局不同，可用编译宏覆盖。
 */
#ifndef TFT_RAM_COLUMN_OFFSET
#define TFT_RAM_COLUMN_OFFSET (2U)
#endif

#ifndef TFT_RAM_ROW_OFFSET
#define TFT_RAM_ROW_OFFSET (1U)
#endif

/** ST7735S 1.8 寸 TFT 的不透明实例。 */
typedef struct TFTInstance TFTInstance;

/** 注册项目固定的 SPI0 ST7735S 屏幕。 */
TFTInstance *TFTRegister(void);

/** 硬件复位、发送 ST7735S 初始化序列并清屏。 */
bool TFTInitialize(TFTInstance *instance);

/** 以下接口操作与 OLED 相同的 128×64 单色逻辑画布。 */
bool TFTClear(TFTInstance *instance, bool pixels_on);
bool TFTSetPixel(TFTInstance *instance,
    uint8_t x, uint8_t y, bool pixel_on);
bool TFTDrawCharacter(TFTInstance *instance,
    uint8_t x, uint8_t y, char character);
bool TFTDrawString(TFTInstance *instance,
    uint8_t x, uint8_t y, const char *text);
bool TFTUpdate(TFTInstance *instance);
bool TFTUpdatePages(TFTInstance *instance,
    uint8_t first_page, uint8_t page_count);
bool TFTSetDisplayEnabled(TFTInstance *instance, bool enabled);
bool TFTSetInverted(TFTInstance *instance, bool inverted);

/** TFT 无模拟对比度寄存器；该值用于调整菜单前景色亮度。 */
bool TFTSetContrast(TFTInstance *instance, uint8_t contrast);

#endif
