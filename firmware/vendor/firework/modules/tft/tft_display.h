/**
 * @file tft_display.h
 * @brief ST7735S TFT 与通用 Display Module 之间的项目默认适配接口。
 */
#ifndef TFT_DISPLAY_H
#define TFT_DISPLAY_H

#include <stdbool.h>

#include "modules/display/display.h"
#include "modules/tft/tft.h"

/** 注册并初始化项目默认的 ST7735S 1.8 寸 TFT。 */
bool TFTDisplayInit(void);

TFTInstance *TFTDisplayGetInstance(void);

/** 返回供通用菜单、波形模块使用的 128×64 显示适配器。 */
DisplayInstance *TFTDisplayGetMenuDisplay(void);

#endif
