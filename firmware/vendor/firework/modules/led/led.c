/* LED Module 把板载状态灯和 RGB 三色灯抽象为带有效电平处理的逻辑设备。 */
#include "modules/led/led.h"

#include <stddef.h>

#include "bsp/gpio/bsp_gpio.h"

struct LEDInstance {
    /* 应用可见的逻辑设备编号。 */
    LED_Device_e device;
    /* LED 实际使用的 GPIO 句柄，硬件细节由 BSP 管理。 */
    BSPGPIOInstance *gpio;
    /* true 表示 GPIO 高电平点亮，false 表示低电平点亮。 */
    bool active_high;
    /* 防止调用方使用尚未成功注册的实例。 */
    bool registered;
};

/* 每种逻辑 LED 使用固定实例，避免动态内存分配。 */
static LEDInstance led_instances[LED_DEVICE_COUNT];

LEDInstance *LEDRegister(LED_Device_e device)
{
    LEDInstance *instance;
    BSP_GPIO_Channel_e gpio_channel;

    /* 先检查枚举范围，避免访问实例数组越界。 */
    if ((device < LED_DEVICE_STATUS) || (device >= LED_DEVICE_COUNT)) {
        return NULL;
    }

    /* 在模块层完成“逻辑 LED”到“板级 GPIO 通道”的映射。 */
    switch (device) {
        case LED_DEVICE_STATUS:
            gpio_channel = BSP_GPIO_CHANNEL_USER_LED_1;
            break;

        case LED_DEVICE_RGB_RED:
            gpio_channel = BSP_GPIO_CHANNEL_RGB_LED_RED;
            break;

        case LED_DEVICE_RGB_GREEN:
            gpio_channel = BSP_GPIO_CHANNEL_RGB_LED_GREEN;
            break;

        case LED_DEVICE_RGB_BLUE:
            gpio_channel = BSP_GPIO_CHANNEL_RGB_LED_BLUE;
            break;

        default:
            return NULL;
    }

    instance = &led_instances[device];
    /* GPIO 注册失败时，不向应用层暴露一个不可用的 LED 实例。 */
    instance->gpio = BSPGPIORegister(gpio_channel);
    if (instance->gpio == NULL) {
        return NULL;
    }

    instance->device = device;
    /* 独立红灯接到 3.3V、由 PA0 灌电流；RGB LED 为共阴极。 */
    instance->active_high = (device != LED_DEVICE_STATUS);
    instance->registered  = true;

    return instance;
}

bool LEDOn(LEDInstance *instance)
{
    if ((instance == NULL) || !instance->registered) {
        return false;
    }

    return BSPGPIOWrite(instance->gpio, instance->active_high);
}

bool LEDOff(LEDInstance *instance)
{
    if ((instance == NULL) || !instance->registered) {
        return false;
    }

    return BSPGPIOWrite(instance->gpio, !instance->active_high);
}

bool LEDToggle(LEDInstance *instance)
{
    /* 对外部传入的不透明句柄做完整有效性检查。 */
    if ((instance == NULL) || !instance->registered) {
        return false;
    }

    /* 实际寄存器操作继续下沉到 BSP，保持模块层与芯片驱动解耦。 */
    return BSPGPIOToggle(instance->gpio);
}
