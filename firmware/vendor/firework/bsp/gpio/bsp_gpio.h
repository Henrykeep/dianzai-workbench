/**
 * @file bsp_gpio.h
 * @brief 逻辑 GPIO 通道注册、读写、翻转和方向控制接口。
 */
#ifndef BSP_GPIO_H
#define BSP_GPIO_H

#include <stdbool.h>

/** LP-MSPM0G3507 板级层向上提供的逻辑 GPIO 通道。 */
typedef enum {
    /* 开发板上的独立红色用户 LED1（PA0）。 */
    BSP_GPIO_CHANNEL_USER_LED_1 = 0,
    /* RGB LED 蓝色通道（PB22）。 */
    BSP_GPIO_CHANNEL_RGB_LED_BLUE,
    /* RGB LED 红色通道（PB26）。 */
    BSP_GPIO_CHANNEL_RGB_LED_RED,
    /* RGB LED 绿色通道（PB27）。 */
    BSP_GPIO_CHANNEL_RGB_LED_GREEN,
    /* 1.8 寸 TFT 的命令/数据选择引脚（PB1）。 */
    BSP_GPIO_CHANNEL_TFT_DC,
    /* 1.8 寸 TFT 的硬件复位引脚（PB4）。 */
    BSP_GPIO_CHANNEL_TFT_RESET,
    /* AD9850 硬件复位引脚（PA1），高电平为复位/无输出。 */
    BSP_GPIO_CHANNEL_AD9850_RESET,
    /* 板载 S1 按键（PA18），按下时为高电平。 */
    BSP_GPIO_CHANNEL_USER_BUTTON_NEXT,
    /* 板载 S2 按键（PB21），按下时为低电平。 */
    BSP_GPIO_CHANNEL_USER_BUTTON_PREVIOUS,
    /* 4x4 矩阵键盘行输出：PB0、PB7、PB12、PB13。 */
    BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_0,
    BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_1,
    BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_2,
    BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_3,
    /* 4x4 矩阵键盘列输入：PA13、PA12、PA29、PA30。 */
    BSP_GPIO_CHANNEL_MATRIX_KEYPAD_COLUMN_0,
    BSP_GPIO_CHANNEL_MATRIX_KEYPAD_COLUMN_1,
    BSP_GPIO_CHANNEL_MATRIX_KEYPAD_COLUMN_2,
    BSP_GPIO_CHANNEL_MATRIX_KEYPAD_COLUMN_3,
    /* 通道总数，同时作为枚举范围上限。 */
    BSP_GPIO_CHANNEL_COUNT
} BSP_GPIO_Channel_e;

/** GPIO 不透明实例，具体硬件信息只保留在 BSP 内部。 */
typedef struct BSPGPIOInstance BSPGPIOInstance;

/** 注册并返回一个板级 GPIO 通道；失败时返回 NULL。 */
BSPGPIOInstance *BSPGPIORegister(BSP_GPIO_Channel_e channel);

/** 将已注册 GPIO 输出为指定逻辑电平。 */
bool BSPGPIOWrite(BSPGPIOInstance *instance, bool high);

/** 翻转已注册 GPIO 的输出电平。 */
bool BSPGPIOToggle(BSPGPIOInstance *instance);

/** 读取已注册 GPIO 的当前逻辑电平。 */
bool BSPGPIORead(BSPGPIOInstance *instance, bool *high);

/**
 * 动态启用或关闭矩阵键盘行的输出驱动；关闭后引脚为高阻输入状态。
 * 其他逻辑通道不允许动态切换方向并返回 false。
 */
bool BSPGPIOSetOutputEnabled(BSPGPIOInstance *instance, bool enabled);

#endif
