/*
 * TFT Display 适配层把 ST7735S 后端绑定到通用 DisplayOperations 操作表。
 */
#include "modules/tft/tft_display.h"

#include <stddef.h>

/* 分别保留硬件实例和提供给菜单的抽象显示实例。 */
static TFTInstance *display_tft;
static DisplayInstance *menu_display;

/* 这些薄适配回调只转换不透明上下文，不改变坐标、颜色或刷新语义。 */
static bool TFTDisplayClear(void *context, bool pixels_on)
{
    return TFTClear((TFTInstance *)context, pixels_on);
}

static bool TFTDisplaySetPixel(
    void *context, uint8_t x, uint8_t y, bool pixel_on)
{
    return TFTSetPixel((TFTInstance *)context, x, y, pixel_on);
}

static bool TFTDisplayDrawCharacter(
    void *context, uint8_t x, uint8_t y, char character)
{
    return TFTDrawCharacter((TFTInstance *)context, x, y, character);
}

static bool TFTDisplayDrawString(
    void *context, uint8_t x, uint8_t y, const char *text)
{
    return TFTDrawString((TFTInstance *)context, x, y, text);
}

static bool TFTDisplayUpdate(void *context)
{
    return TFTUpdate((TFTInstance *)context);
}

static bool TFTDisplayUpdatePages(
    void *context, uint8_t first_page, uint8_t page_count)
{
    return TFTUpdatePages(
        (TFTInstance *)context, first_page, page_count);
}

static bool TFTDisplaySetEnabled(void *context, bool enabled)
{
    return TFTSetDisplayEnabled((TFTInstance *)context, enabled);
}

static bool TFTDisplaySetInverted(void *context, bool inverted)
{
    return TFTSetInverted((TFTInstance *)context, inverted);
}

static bool TFTDisplaySetContrast(void *context, uint8_t contrast)
{
    return TFTSetContrast((TFTInstance *)context, contrast);
}

static const DisplayOperations tft_display_operations = {
    TFTDisplayClear,
    TFTDisplaySetPixel,
    TFTDisplayDrawCharacter,
    TFTDisplayDrawString,
    TFTDisplayUpdate,
    TFTDisplayUpdatePages,
    TFTDisplaySetEnabled,
    TFTDisplaySetInverted,
    TFTDisplaySetContrast
};

bool TFTDisplayInit(void)
{
    TFTInstance *instance;

    /* 已成功绑定后重复初始化保持幂等。 */
    if (display_tft != NULL) {
        return true;
    }

    instance = TFTRegister();
    if ((instance == NULL) || !TFTInitialize(instance)) {
        return false;
    }

    /* 硬件初始化成功后再注册抽象层；注册失败时立即关闭面板。 */
    menu_display = DisplayRegister(instance, &tft_display_operations);
    if (menu_display == NULL) {
        (void)TFTSetDisplayEnabled(instance, false);
        return false;
    }

    display_tft = instance;
    return true;
}

TFTInstance *TFTDisplayGetInstance(void)
{
    return display_tft;
}

DisplayInstance *TFTDisplayGetMenuDisplay(void)
{
    return menu_display;
}
