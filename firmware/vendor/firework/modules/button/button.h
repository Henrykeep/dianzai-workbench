/* 板载按键硬件无关接口：统一有效电平并提供软件防抖事件。 */
#ifndef BUTTON_H
#define BUTTON_H

#include <stdbool.h>
#include <stdint.h>

/** 应用可使用的逻辑板载按键。 */
typedef enum {
    /* PA18 / S1，用于菜单移动。 */
    BUTTON_DEVICE_NEXT = 0,
    /* PB21 / S2，用于菜单向前移动和返回。 */
    BUTTON_DEVICE_PREVIOUS,
    /* 逻辑按键数量，同时作为枚举范围上限。 */
    BUTTON_DEVICE_COUNT
} Button_Device_e;

/** 软件防抖后产生的按键事件。 */
typedef enum {
    BUTTON_EVENT_NONE = 0,
    BUTTON_EVENT_SHORT_PRESS,
    BUTTON_EVENT_LONG_PRESS
} Button_Event_e;

/** Button 模块的不透明实例。 */
typedef struct ButtonInstance ButtonInstance;

/** 注册指定板载按键；失败时返回 NULL。 */
ButtonInstance *ButtonRegister(Button_Device_e device);

/** 读取按键当前是否处于按下状态，并自动处理有效电平差异。 */
bool ButtonIsPressed(ButtonInstance *instance, bool *pressed);

/**
 * @brief 周期调用按键状态机，返回本周期产生的短按或长按事件。
 *
 * @param elapsed_ms 距离上次调用经过的毫秒数，推荐固定为 10 ms。
 */
Button_Event_e ButtonProcess(
    ButtonInstance *instance, uint32_t elapsed_ms);

#endif
