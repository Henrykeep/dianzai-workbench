/* 将板载 GPIO 按键转换为经过防抖的短按、长按逻辑事件。 */
#include "modules/button/button.h"

#include <stddef.h>

#include "bsp/gpio/bsp_gpio.h"

/* 时间参数单位均为毫秒：原始电平稳定 30 ms 后生效，持续 800 ms 报告长按。 */
#define BUTTON_DEBOUNCE_TIME_MS  (30UL)
#define BUTTON_LONG_PRESS_TIME_MS (800UL)

struct ButtonInstance {
    /* 应用可见的逻辑按键编号。 */
    Button_Device_e device;
    /* 按键使用的板级 GPIO 句柄。 */
    BSPGPIOInstance *gpio;
    /* true 表示 GPIO 高电平代表按下。 */
    bool active_high;
    /* 软件防抖和长按识别状态。 */
    bool last_raw_pressed;
    bool stable_pressed;
    bool long_press_reported;
    uint32_t debounce_elapsed_ms;
    uint32_t pressed_elapsed_ms;
    /* 防止使用尚未成功注册的实例。 */
    bool registered;
};

/* 两个板载按键使用固定静态实例。 */
static ButtonInstance button_instances[BUTTON_DEVICE_COUNT];

static bool ButtonIsValid(const ButtonInstance *instance);
static uint32_t ButtonSaturatingAdd(uint32_t value, uint32_t increment);

/* 注册逻辑按键并记录其板级通道和有效电平。 */
ButtonInstance *ButtonRegister(Button_Device_e device)
{
    BSP_GPIO_Channel_e gpio_channel;
    ButtonInstance *instance;
    bool initial_pressed;

    if ((device < BUTTON_DEVICE_NEXT) || (device >= BUTTON_DEVICE_COUNT)) {
        return NULL;
    }

    switch (device) {
        case BUTTON_DEVICE_NEXT:
            gpio_channel = BSP_GPIO_CHANNEL_USER_BUTTON_NEXT;
            break;

        case BUTTON_DEVICE_PREVIOUS:
            gpio_channel = BSP_GPIO_CHANNEL_USER_BUTTON_PREVIOUS;
            break;

        default:
            return NULL;
    }

    instance = &button_instances[device];
    if (instance->registered) {
        return instance;
    }

    instance->gpio = BSPGPIORegister(gpio_channel);
    if (instance->gpio == NULL) {
        return NULL;
    }

    instance->device      = device;
    instance->active_high = device == BUTTON_DEVICE_NEXT;
    instance->registered  = true;

    if (!ButtonIsPressed(instance, &initial_pressed)) {
        instance->registered = false;
        return NULL;
    }

    instance->last_raw_pressed   = initial_pressed;
    instance->stable_pressed     = initial_pressed;
    instance->long_press_reported = false;
    instance->debounce_elapsed_ms = 0U;
    instance->pressed_elapsed_ms  = 0U;
    return instance;
}

/* 读取物理 GPIO，并转换成与硬件有效电平无关的按下状态。 */
bool ButtonIsPressed(ButtonInstance *instance, bool *pressed)
{
    bool high;

    if (!ButtonIsValid(instance) || (pressed == NULL) ||
        !BSPGPIORead(instance->gpio, &high)) {
        return false;
    }

    *pressed = instance->active_high ? high : !high;
    return true;
}

/* 执行软件防抖，并在释放时报告短按、达到阈值时报告一次长按。 */
Button_Event_e ButtonProcess(
    ButtonInstance *instance, uint32_t elapsed_ms)
{
    bool raw_pressed;

    if (!ButtonIsValid(instance) || (elapsed_ms == 0U) ||
        !ButtonIsPressed(instance, &raw_pressed)) {
        return BUTTON_EVENT_NONE;
    }

    if (raw_pressed != instance->last_raw_pressed) {
        instance->last_raw_pressed    = raw_pressed;
        instance->debounce_elapsed_ms = 0U;
        return BUTTON_EVENT_NONE;
    }

    if (raw_pressed != instance->stable_pressed) {
        instance->debounce_elapsed_ms = ButtonSaturatingAdd(
            instance->debounce_elapsed_ms, elapsed_ms);

        if (instance->debounce_elapsed_ms < BUTTON_DEBOUNCE_TIME_MS) {
            return BUTTON_EVENT_NONE;
        }

        instance->stable_pressed      = raw_pressed;
        instance->debounce_elapsed_ms = 0U;

        if (raw_pressed) {
            instance->pressed_elapsed_ms   = 0U;
            instance->long_press_reported  = false;
        } else {
            instance->pressed_elapsed_ms = 0U;
            if (!instance->long_press_reported) {
                return BUTTON_EVENT_SHORT_PRESS;
            }
        }
    }

    if (instance->stable_pressed && !instance->long_press_reported) {
        instance->pressed_elapsed_ms = ButtonSaturatingAdd(
            instance->pressed_elapsed_ms, elapsed_ms);

        if (instance->pressed_elapsed_ms >= BUTTON_LONG_PRESS_TIME_MS) {
            instance->long_press_reported = true;
            return BUTTON_EVENT_LONG_PRESS;
        }
    }

    return BUTTON_EVENT_NONE;
}

/* 检查 Button 不透明实例是否已经成功注册。 */
static bool ButtonIsValid(const ButtonInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->device >= BUTTON_DEVICE_NEXT) &&
           (instance->device < BUTTON_DEVICE_COUNT) &&
           (instance->gpio != NULL);
}

/* 对毫秒计数执行饱和加法，避免长时间按住时无符号整数回绕。 */
static uint32_t ButtonSaturatingAdd(uint32_t value, uint32_t increment)
{
    return (UINT32_MAX - value < increment) ? UINT32_MAX
                                             : value + increment;
}
