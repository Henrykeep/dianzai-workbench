/* GPIO BSP 将稳定的逻辑通道映射到 SysConfig 端口和引脚，并统一校验读写方向。 */
#include "bsp/gpio/bsp_gpio.h"

#include <stddef.h>

#include "ti_msp_dl_config.h"

struct BSPGPIOInstance {
    /* 板级逻辑通道，由 BSP 负责映射到具体端口和引脚。 */
    BSP_GPIO_Channel_e channel;
    /* 标记该静态实例是否已经完成注册。 */
    bool registered;
    /* true 表示该通道允许执行写入和翻转操作。 */
    bool output;
};

/* GPIO 实例采用静态分配，适合资源固定的嵌入式系统。 */
static BSPGPIOInstance gpio_instances[BSP_GPIO_CHANNEL_COUNT];

static bool BSPGPIOResolve(const BSPGPIOInstance *instance,
    GPIO_Regs **port, uint32_t *pin);
static bool BSPGPIOChannelIsOutput(BSP_GPIO_Channel_e channel);
static bool BSPGPIOChannelSupportsDirectionControl(
    BSP_GPIO_Channel_e channel);

BSPGPIOInstance *BSPGPIORegister(BSP_GPIO_Channel_e channel)
{
    BSPGPIOInstance *instance;

    /* 非法通道会导致数组越界，因此注册前必须校验。 */
    if ((channel < BSP_GPIO_CHANNEL_USER_LED_1) ||
        (channel >= BSP_GPIO_CHANNEL_COUNT)) {
        return NULL;
    }

    instance             = &gpio_instances[channel];
    instance->channel    = channel;
    instance->output     = BSPGPIOChannelIsOutput(channel);
    instance->registered = true;

    return instance;
}

bool BSPGPIOWrite(BSPGPIOInstance *instance, bool high)
{
    GPIO_Regs *port;
    uint32_t pin;

    /* 拒绝空指针以及未经注册的 GPIO 句柄。 */
    if (!BSPGPIOResolve(instance, &port, &pin) || !instance->output) {
        return false;
    }

    if (high) {
        DL_GPIO_setPins(port, pin);
    } else {
        DL_GPIO_clearPins(port, pin);
    }

    return true;
}

bool BSPGPIOToggle(BSPGPIOInstance *instance)
{
    GPIO_Regs *port;
    uint32_t pin;

    /* 通道解析与有效性检查集中在同一个私有函数中。 */
    if (!BSPGPIOResolve(instance, &port, &pin) || !instance->output) {
        return false;
    }

    DL_GPIO_togglePins(port, pin);
    return true;
}

bool BSPGPIORead(BSPGPIOInstance *instance, bool *high)
{
    GPIO_Regs *port;
    uint32_t pin;

    if ((high == NULL) || !BSPGPIOResolve(instance, &port, &pin)) {
        return false;
    }

    *high = (DL_GPIO_readPins(port, pin) & pin) != 0U;
    return true;
}

bool BSPGPIOSetOutputEnabled(BSPGPIOInstance *instance, bool enabled)
{
    GPIO_Regs *port;
    uint32_t pin;

    if (!BSPGPIOResolve(instance, &port, &pin) ||
        !BSPGPIOChannelSupportsDirectionControl(instance->channel)) {
        return false;
    }

    if (enabled) {
        DL_GPIO_enableOutput(port, pin);
    } else {
        DL_GPIO_disableOutput(port, pin);
    }
    return true;
}

static bool BSPGPIOResolve(const BSPGPIOInstance *instance,
    GPIO_Regs **port, uint32_t *pin)
{
    if ((instance == NULL) || !instance->registered || (port == NULL) ||
        (pin == NULL)) {
        return false;
    }

    /* 仅 BSP 知道逻辑通道对应的真实 SysConfig 端口和引脚。 */
    switch (instance->channel) {
        case BSP_GPIO_CHANNEL_USER_LED_1:
            *port = GPIO_LEDS_USER_LED_1_PORT;
            *pin  = GPIO_LEDS_USER_LED_1_PIN;
            return true;

        case BSP_GPIO_CHANNEL_RGB_LED_BLUE:
            *port = GPIO_LEDS_RGB_LED_BLUE_PORT;
            *pin  = GPIO_LEDS_RGB_LED_BLUE_PIN;
            return true;

        case BSP_GPIO_CHANNEL_RGB_LED_RED:
            *port = GPIO_LEDS_RGB_LED_RED_PORT;
            *pin  = GPIO_LEDS_RGB_LED_RED_PIN;
            return true;

        case BSP_GPIO_CHANNEL_RGB_LED_GREEN:
            *port = GPIO_LEDS_RGB_LED_GREEN_PORT;
            *pin  = GPIO_LEDS_RGB_LED_GREEN_PIN;
            return true;

        case BSP_GPIO_CHANNEL_TFT_DC:
            *port = GPIO_TFT_PORT;
            *pin  = GPIO_TFT_TFT_DC_PIN;
            return true;

        case BSP_GPIO_CHANNEL_TFT_RESET:
            *port = GPIO_TFT_PORT;
            *pin  = GPIO_TFT_TFT_RESET_PIN;
            return true;

        case BSP_GPIO_CHANNEL_AD9850_RESET:
            *port = GPIO_AD9850_PORT;
            *pin  = GPIO_AD9850_AD9850_RESET_PIN;
            return true;

        case BSP_GPIO_CHANNEL_USER_BUTTON_NEXT:
            *port = GPIO_LEDS_USER_BUTTON_NEXT_PORT;
            *pin  = GPIO_LEDS_USER_BUTTON_NEXT_PIN;
            return true;

        case BSP_GPIO_CHANNEL_USER_BUTTON_PREVIOUS:
            *port = GPIO_LEDS_USER_BUTTON_PREVIOUS_PORT;
            *pin  = GPIO_LEDS_USER_BUTTON_PREVIOUS_PIN;
            return true;

        case BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_0:
            *port = GPIO_MATRIX_KEYPAD_ROW_0_PORT;
            *pin  = GPIO_MATRIX_KEYPAD_ROW_0_PIN;
            return true;

        case BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_1:
            *port = GPIO_MATRIX_KEYPAD_ROW_1_PORT;
            *pin  = GPIO_MATRIX_KEYPAD_ROW_1_PIN;
            return true;

        case BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_2:
            *port = GPIO_MATRIX_KEYPAD_ROW_2_PORT;
            *pin  = GPIO_MATRIX_KEYPAD_ROW_2_PIN;
            return true;

        case BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_3:
            *port = GPIO_MATRIX_KEYPAD_ROW_3_PORT;
            *pin  = GPIO_MATRIX_KEYPAD_ROW_3_PIN;
            return true;

        case BSP_GPIO_CHANNEL_MATRIX_KEYPAD_COLUMN_0:
            *port = GPIO_MATRIX_KEYPAD_COLUMN_0_PORT;
            *pin  = GPIO_MATRIX_KEYPAD_COLUMN_0_PIN;
            return true;

        case BSP_GPIO_CHANNEL_MATRIX_KEYPAD_COLUMN_1:
            *port = GPIO_MATRIX_KEYPAD_COLUMN_1_PORT;
            *pin  = GPIO_MATRIX_KEYPAD_COLUMN_1_PIN;
            return true;

        case BSP_GPIO_CHANNEL_MATRIX_KEYPAD_COLUMN_2:
            *port = GPIO_MATRIX_KEYPAD_COLUMN_2_PORT;
            *pin  = GPIO_MATRIX_KEYPAD_COLUMN_2_PIN;
            return true;

        case BSP_GPIO_CHANNEL_MATRIX_KEYPAD_COLUMN_3:
            *port = GPIO_MATRIX_KEYPAD_COLUMN_3_PORT;
            *pin  = GPIO_MATRIX_KEYPAD_COLUMN_3_PIN;
            return true;

        default:
            return false;
    }
}

/* 输出能力由通道用途决定，避免依赖枚举排列顺序。 */
static bool BSPGPIOChannelIsOutput(BSP_GPIO_Channel_e channel)
{
    switch (channel) {
        case BSP_GPIO_CHANNEL_USER_LED_1:
        case BSP_GPIO_CHANNEL_RGB_LED_BLUE:
        case BSP_GPIO_CHANNEL_RGB_LED_RED:
        case BSP_GPIO_CHANNEL_RGB_LED_GREEN:
        case BSP_GPIO_CHANNEL_TFT_DC:
        case BSP_GPIO_CHANNEL_TFT_RESET:
        case BSP_GPIO_CHANNEL_AD9850_RESET:
        case BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_0:
        case BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_1:
        case BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_2:
        case BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_3:
            return true;

        default:
            return false;
    }
}

/* 只有矩阵行需要在扫描期间切换输出和高阻状态。 */
static bool BSPGPIOChannelSupportsDirectionControl(
    BSP_GPIO_Channel_e channel)
{
    return (channel >= BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_0) &&
           (channel <= BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_3);
}
