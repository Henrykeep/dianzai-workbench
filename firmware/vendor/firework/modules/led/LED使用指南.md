# LED Module 使用指南

`modules/led/` 将板载独立状态灯和RGB LED封装为统一的点亮、熄灭和翻转接口。

## 1. LED映射

| 逻辑设备 | 引脚 | 说明 |
|---|---|---|
| `LED_DEVICE_STATUS` | PA0 | 独立红色LED，低电平点亮 |
| `LED_DEVICE_RGB_RED` | PB26 | RGB红色通道，高电平点亮 |
| `LED_DEVICE_RGB_GREEN` | PB27 | RGB绿色通道，高电平点亮 |
| `LED_DEVICE_RGB_BLUE` | PB22 | RGB蓝色通道，高电平点亮 |

有效电平差异由Module自动处理，应用不需要判断共阳极或共阴极逻辑。

## 2. 注册和控制

```c
#include "modules/led/led.h"

static LEDInstance *status_led;

bool ExampleLEDInit(void)
{
    status_led = LEDRegister(LED_DEVICE_STATUS);
    return (status_led != NULL) && LEDOff(status_led);
}
```

```c
(void)LEDOn(status_led);
(void)LEDOff(status_led);
(void)LEDToggle(status_led);
```

同一逻辑LED使用固定静态实例，不申请动态内存。

## 3. FreeRTOS闪烁示例

```c
for (;;) {
    (void)LEDToggle(status_led);
    vTaskDelay(pdMS_TO_TICKS(500U));
}
```

## 4. 使用注意事项

- Module内部不使用互斥锁，建议每个LED由一个任务负责，或由应用层统一协调访问。
- 不要在多个任务中同时执行翻转操作，否则最终状态可能难以预测。
- `LEDOn()` 和 `LEDOff()` 可以重复调用，接口会写入确定逻辑状态。
- 当前实现面向板载LED；外接大功率LED必须使用限流电阻和合适的驱动器件。
- 如果独立红灯逻辑与RGB灯相反属于正常硬件差异，Module已经自动转换。
