/**
 * @file led.h
 * @brief 板载状态灯与 RGB LED 的逻辑注册和开关接口。
 */
#ifndef LED_H
#define LED_H

#include <stdbool.h>

/** 应用层可使用的逻辑 LED，枚举值不代表具体 GPIO 引脚。 */
typedef enum {
    /* 独立红色系统状态灯。 */
    LED_DEVICE_STATUS = 0,
    /* RGB LED 的红色通道。 */
    LED_DEVICE_RGB_RED,
    /* RGB LED 的绿色通道。 */
    LED_DEVICE_RGB_GREEN,
    /* RGB LED 的蓝色通道。 */
    LED_DEVICE_RGB_BLUE,
    /* 逻辑 LED 数量，同时作为枚举范围上限。 */
    LED_DEVICE_COUNT
} LED_Device_e;

/** LED 模块的不透明实例，调用方无需了解其内部成员。 */
typedef struct LEDInstance LEDInstance;

/** 注册指定逻辑 LED；失败时返回 NULL。 */
LEDInstance *LEDRegister(LED_Device_e device);

/** 点亮指定 LED，并自动处理板级有效电平差异。 */
bool LEDOn(LEDInstance *instance);

/** 熄灭指定 LED，并自动处理板级有效电平差异。 */
bool LEDOff(LEDInstance *instance);

/** 翻转逻辑 LED 电平，不向上层暴露 GPIO 或 DriverLib 细节。 */
bool LEDToggle(LEDInstance *instance);

#endif
