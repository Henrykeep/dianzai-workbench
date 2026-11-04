# Button Module 使用指南

`modules/button/` 统一处理两个板载按键的有效电平、软件防抖、短按和长按识别。

## 1. 按键映射

| 逻辑设备 | 板载按键 | 引脚 | 按下电平 |
|---|---|---|---|
| `BUTTON_DEVICE_NEXT` | S1 | PA18 | 高电平 |
| `BUTTON_DEVICE_PREVIOUS` | S2 | PB21 | 低电平 |

有效电平差异由Module自动处理，应用只使用统一的“按下/释放”状态。

## 2. 注册按键

```c
#include "modules/button/button.h"

static ButtonInstance *button_next;
static ButtonInstance *button_previous;

bool ExampleButtonInit(void)
{
    button_next = ButtonRegister(BUTTON_DEVICE_NEXT);
    button_previous = ButtonRegister(BUTTON_DEVICE_PREVIOUS);

    return (button_next != NULL) && (button_previous != NULL);
}
```

模块使用固定静态实例，不申请动态内存。同一设备重复注册会取得同一个逻辑按键。

## 3. 读取即时状态

```c
bool pressed;

if (ButtonIsPressed(button_next, &pressed) && pressed) {
    /* S1当前处于按下状态。 */
}
```

该接口只读取当前状态，不执行防抖，也不产生短按或长按事件。

## 4. 周期处理按键事件

建议在固定 `10 ms` 周期任务中调用：

```c
Button_Event_e event;

event = ButtonProcess(button_next, 10U);

if (event == BUTTON_EVENT_SHORT_PRESS) {
    /* 按键释放时产生一次短按事件。 */
} else if (event == BUTTON_EVENT_LONG_PRESS) {
    /* 按住达到长按时间时产生一次长按事件。 */
}
```

当前固定参数：

- 防抖时间：`30 ms`
- 长按时间：`800 ms`
- 长按事件每次按住只报告一次。
- 已报告长按后再释放，不会额外报告短按。

`elapsed_ms` 必须填写距离上一次调用经过的真实毫秒数。任务周期不是10ms时，应传入
对应值，而不是固定写10。

## 5. FreeRTOS任务示例

```c
TickType_t next_wake_time = xTaskGetTickCount();

for (;;) {
    Button_Event_e event = ButtonProcess(button_next, 10U);

    if (event == BUTTON_EVENT_SHORT_PRESS) {
        /* 执行业务动作。 */
    }

    vTaskDelayUntil(&next_wake_time, pdMS_TO_TICKS(10U));
}
```

## 6. 使用限制

- 按键状态机应固定由同一个任务调用，避免多任务重复消费事件。
- 不要在GPIO ISR和任务中同时调用 `ButtonProcess()`。
- 如果按键一直处于按下状态，检查PA18/PB21接线、上下拉和有效电平配置。
- 改变轮询周期不需要修改模块常量，但必须传入正确的 `elapsed_ms`。
