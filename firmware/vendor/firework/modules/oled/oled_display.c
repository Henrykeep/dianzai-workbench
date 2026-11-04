/*
 * OLED 显示适配层：把通用 DisplayOperations 转发到 SSD1306 驱动，
 * 并维护项目默认 OLED 与通用显示实例的静态绑定关系。
 */
#include "modules/oled/oled_display.h"

#include <stddef.h>

#define OLED_DISPLAY_I2C_ADDRESS (0x3CU)

/* 初始化成功后两者在整个固件运行期保持有效，不需要动态释放。 */
static OLEDInstance *display_oled;
static DisplayInstance *menu_display;

/* 以下轻量回调只负责还原后端上下文并转发到 OLED 接口。 */
static bool OLEDDisplayClear(void *context, bool pixels_on)
{
    return OLEDClear((OLEDInstance *)context, pixels_on);
}

static bool OLEDDisplaySetPixel(
    void *context, uint8_t x, uint8_t y, bool pixel_on)
{
    return OLEDSetPixel(
        (OLEDInstance *)context, x, y, pixel_on);
}

static bool OLEDDisplayDrawCharacter(
    void *context, uint8_t x, uint8_t y, char character)
{
    return OLEDDrawCharacter(
        (OLEDInstance *)context, x, y, character);
}

static bool OLEDDisplayDrawString(
    void *context, uint8_t x, uint8_t y, const char *text)
{
    return OLEDDrawString((OLEDInstance *)context, x, y, text);
}

static bool OLEDDisplayUpdate(void *context)
{
    return OLEDUpdate((OLEDInstance *)context);
}

static bool OLEDDisplayUpdatePages(
    void *context, uint8_t first_page, uint8_t page_count)
{
    return OLEDUpdatePages(
        (OLEDInstance *)context, first_page, page_count);
}

static bool OLEDDisplaySetEnabled(void *context, bool enabled)
{
    return OLEDSetDisplayEnabled((OLEDInstance *)context, enabled);
}

static bool OLEDDisplaySetInverted(void *context, bool inverted)
{
    return OLEDSetInverted((OLEDInstance *)context, inverted);
}

static bool OLEDDisplaySetContrast(void *context, uint8_t contrast)
{
    return OLEDSetContrast((OLEDInstance *)context, contrast);
}

/* 通用显示层通过此操作表访问 OLED，不感知其 I2C 和帧缓冲实现。 */
static const DisplayOperations oled_display_operations = {
    OLEDDisplayClear,
    OLEDDisplaySetPixel,
    OLEDDisplayDrawCharacter,
    OLEDDisplayDrawString,
    OLEDDisplayUpdate,
    OLEDDisplayUpdatePages,
    OLEDDisplaySetEnabled,
    OLEDDisplaySetInverted,
    OLEDDisplaySetContrast
};

/* 注册并初始化项目默认的 SSD1306 OLED 实例。 */
bool OLEDDisplayInit(void)
{
    OLEDInstance *instance;

    /* 已成功初始化时保持幂等，避免重复注册显示后端。 */
    if (display_oled != NULL) {
        return true;
    }

    instance = OLEDRegister(OLED_DISPLAY_I2C_ADDRESS);
    if ((instance == NULL) || !OLEDInitialize(instance)) {
        return false;
    }

    menu_display = DisplayRegister(
        instance, &oled_display_operations);
    if (menu_display == NULL) {
        (void)OLEDSetDisplayEnabled(instance, false);
        return false;
    }

    display_oled = instance;
    return true;
}

/* 向 Application 返回已经初始化完成的 OLED 实例。 */
OLEDInstance *OLEDDisplayGetInstance(void)
{
    return display_oled;
}

DisplayInstance *OLEDDisplayGetMenuDisplay(void)
{
    /* 初始化失败或尚未调用 OLEDDisplayInit 时返回 NULL。 */
    return menu_display;
}
