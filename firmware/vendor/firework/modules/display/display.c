/*
 * Display Module 以操作表屏蔽 OLED/TFT 差异，为菜单和波形提供统一逻辑画布接口。
 */
#include "modules/display/display.h"

#include <stddef.h>

struct DisplayInstance {
    /* 后端私有实例，由 OLED/TFT 适配层持有。 */
    void *context;
    /* 完整操作表在注册时统一校验，此后转发接口无需重复检查每个回调。 */
    const DisplayOperations *operations;
    bool registered;
};

/* 产品构建只启用一个显示后端，因此使用单一静态适配实例。 */
static DisplayInstance display_instance;

/* 防止注册不完整的后端后在页面刷新路径解引用空回调。 */
static bool DisplayOperationsAreValid(const DisplayOperations *operations)
{
    return (operations != NULL) && (operations->clear != NULL) &&
           (operations->set_pixel != NULL) &&
           (operations->draw_character != NULL) &&
           (operations->draw_string != NULL) &&
           (operations->update != NULL) &&
           (operations->update_pages != NULL) &&
           (operations->set_enabled != NULL) &&
           (operations->set_inverted != NULL) &&
           (operations->set_contrast != NULL);
}

static bool DisplayIsValid(const DisplayInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->context != NULL) &&
           DisplayOperationsAreValid(instance->operations);
}

DisplayInstance *DisplayRegister(
    void *context, const DisplayOperations *operations)
{
    if ((context == NULL) || !DisplayOperationsAreValid(operations)) {
        return NULL;
    }
    /* 重复注册同一后端保持幂等，尝试替换已注册后端则拒绝。 */
    if (display_instance.registered) {
        return ((display_instance.context == context) &&
                   (display_instance.operations == operations))
                   ? &display_instance
                   : NULL;
    }

    display_instance.context    = context;
    display_instance.operations = operations;
    display_instance.registered = true;
    return &display_instance;
}

bool DisplayClear(DisplayInstance *instance, bool pixels_on)
{
    /* 以下接口只负责统一校验并把调用原样转发给当前显示后端。 */
    return DisplayIsValid(instance) &&
           instance->operations->clear(instance->context, pixels_on);
}

bool DisplaySetPixel(DisplayInstance *instance,
    uint8_t x, uint8_t y, bool pixel_on)
{
    return DisplayIsValid(instance) &&
           instance->operations->set_pixel(
               instance->context, x, y, pixel_on);
}

bool DisplayDrawCharacter(DisplayInstance *instance,
    uint8_t x, uint8_t y, char character)
{
    return DisplayIsValid(instance) &&
           instance->operations->draw_character(
               instance->context, x, y, character);
}

bool DisplayDrawString(DisplayInstance *instance,
    uint8_t x, uint8_t y, const char *text)
{
    return DisplayIsValid(instance) &&
           instance->operations->draw_string(
               instance->context, x, y, text);
}

bool DisplayUpdate(DisplayInstance *instance)
{
    return DisplayIsValid(instance) &&
           instance->operations->update(instance->context);
}

bool DisplayUpdatePages(DisplayInstance *instance,
    uint8_t first_page, uint8_t page_count)
{
    return DisplayIsValid(instance) &&
           instance->operations->update_pages(
               instance->context, first_page, page_count);
}

bool DisplaySetEnabled(DisplayInstance *instance, bool enabled)
{
    return DisplayIsValid(instance) &&
           instance->operations->set_enabled(
               instance->context, enabled);
}

bool DisplaySetInverted(DisplayInstance *instance, bool inverted)
{
    return DisplayIsValid(instance) &&
           instance->operations->set_inverted(
               instance->context, inverted);
}

bool DisplaySetContrast(DisplayInstance *instance, uint8_t contrast)
{
    return DisplayIsValid(instance) &&
           instance->operations->set_contrast(
               instance->context, contrast);
}
