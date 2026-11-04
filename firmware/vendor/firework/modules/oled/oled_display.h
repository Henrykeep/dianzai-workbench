/**
 * @file oled_display.h
 * @brief 将默认 SSD1306 OLED 适配为菜单和波形共用的 Display 接口。
 */
#ifndef OLED_DISPLAY_H
#define OLED_DISPLAY_H

#include <stdbool.h>

#include "modules/display/display.h"
#include "modules/oled/oled.h"

/** 使用项目默认 I2C 地址注册并初始化 SSD1306 OLED。 */
bool OLEDDisplayInit(void);

/** 返回已初始化的默认 OLED 实例；尚未初始化时返回 NULL。 */
OLEDInstance *OLEDDisplayGetInstance(void);

/** 返回供通用菜单、波形模块使用的 128×64 显示适配器。 */
DisplayInstance *OLEDDisplayGetMenuDisplay(void);

#endif
