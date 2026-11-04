/**
 * @file display.h
 * @brief OLED/TFT 共用的 128×64 逻辑显示抽象及操作表接口。
 */
#ifndef DISPLAY_H
#define DISPLAY_H

#include <stdbool.h>
#include <stdint.h>

/* 菜单统一使用 128×64 单色逻辑画布，具体面板由显示后端负责转换。 */
#define DISPLAY_WIDTH  (128U)
#define DISPLAY_HEIGHT (64U)

/** 菜单、波形等通用模块使用的不透明显示实例。 */
typedef struct DisplayInstance DisplayInstance;

/**
 * 显示后端操作表。OLED 和 TFT 适配器各提供一份，业务模块不感知总线类型。
 * context 由后端拥有，生命周期必须覆盖 DisplayInstance 的整个使用期。
 */
typedef struct {
    bool (*clear)(void *context, bool pixels_on);
    bool (*set_pixel)(void *context, uint8_t x, uint8_t y, bool pixel_on);
    bool (*draw_character)(
        void *context, uint8_t x, uint8_t y, char character);
    bool (*draw_string)(
        void *context, uint8_t x, uint8_t y, const char *text);
    bool (*update)(void *context);
    bool (*update_pages)(
        void *context, uint8_t first_page, uint8_t page_count);
    bool (*set_enabled)(void *context, bool enabled);
    bool (*set_inverted)(void *context, bool inverted);
    bool (*set_contrast)(void *context, uint8_t contrast);
} DisplayOperations;

/** 绑定一个已初始化的显示后端；本项目同一固件只允许绑定一个。 */
DisplayInstance *DisplayRegister(
    void *context, const DisplayOperations *operations);

bool DisplayClear(DisplayInstance *instance, bool pixels_on);
/* 以下绘制、刷新和面板控制接口均转发到注册的显示后端。 */
bool DisplaySetPixel(DisplayInstance *instance,
    uint8_t x, uint8_t y, bool pixel_on);
bool DisplayDrawCharacter(DisplayInstance *instance,
    uint8_t x, uint8_t y, char character);
bool DisplayDrawString(DisplayInstance *instance,
    uint8_t x, uint8_t y, const char *text);
bool DisplayUpdate(DisplayInstance *instance);
bool DisplayUpdatePages(DisplayInstance *instance,
    uint8_t first_page, uint8_t page_count);
bool DisplaySetEnabled(DisplayInstance *instance, bool enabled);
bool DisplaySetInverted(DisplayInstance *instance, bool inverted);
bool DisplaySetContrast(DisplayInstance *instance, uint8_t contrast);

#endif
