# Blinky LED 使用指南

`modules/led/blinky.*` 在 LED Module 之上实现 FreeRTOS LED 轮转任务，
依次点亮独立状态灯和 RGB LED 三个颜色通道。

## 1. 目录文件

| 文件 | 作用 |
| --- | --- |
| `blinky.h` | 对外声明 `BlinkyInit()` 初始化接口 |
| `blinky.c` | 注册 LED、创建 FreeRTOS 任务并实现轮转效果 |

Module 不直接访问 GPIO 寄存器或 TI DriverLib。

## 2. LED 与引脚映射

| 逻辑 LED | 物理引脚 | 说明 |
| --- | --- | --- |
| `LED_DEVICE_STATUS` | PA0 | 开发板独立红色用户 LED1 |
| `LED_DEVICE_RGB_RED` | PB26 | RGB LED 红色通道 |
| `LED_DEVICE_RGB_GREEN` | PB27 | RGB LED 绿色通道 |
| `LED_DEVICE_RGB_BLUE` | PB22 | RGB LED 蓝色通道 |

独立状态灯是低电平点亮，RGB LED 是高电平点亮。`LEDOn()` 和 `LEDOff()` 会在模块内部自动处理有效电平差异，应用代码不需要区分。

## 3. 启用 Blinky Module

需要 LED 演示的 Application 可在自己的初始化函数中调用：

```c
#include "modules/led/blinky.h"

if (!BlinkyInit()) {
    /* 初始化失败。 */
}
```

`BSPInit()` 必须在 `BlinkyInit()` 之前执行，因为 GPIO 时钟、引脚复用和
初始状态由 BSP/SysConfig 负责配置。`app_config.h` 不再直接控制
Blinky Module。

## 4. 初始化流程

`BlinkyInit()` 会遍历并注册全部四路逻辑 LED：

```c
for (device = LED_DEVICE_STATUS;
     device < LED_DEVICE_COUNT;
     ++device) {
    leds[device] = LEDRegister(device);

    if ((leds[device] == NULL) ||
        !LEDOff(leds[device])) {
        return false;
    }
}
```

每个 LED 注册成功后会被统一设置为熄灭状态。任意一路注册或关闭失败，`BlinkyInit()` 都会返回 `false`。

随后使用静态任务控制块和静态栈创建 FreeRTOS 任务：

```c
if (xTaskCreateStatic(BlinkyTask, "Blinky",
        BLINKY_TASK_STACK_SIZE, NULL, BLINKY_TASK_PRIORITY,
        blinky_task_stack, &blinky_task_control) == NULL) {
    return false;
}

blinky_task_created = true;
return true;
```

## 5. 默认运行效果

任务按照以下顺序循环：

```text
独立红色状态灯
        ↓
RGB 红色
        ↓
RGB 绿色
        ↓
RGB 蓝色
        ↓
重新回到独立红色状态灯
```

每一路点亮 250 ms，然后熄灭并切换到下一路：

```c
#define BLINKY_STEP_PERIOD_MS (250UL)
```

完整一轮包含四个 LED，因此默认轮转周期约为：

```text
250 ms × 4 = 1000 ms
```

## 6. 修改切换速度

修改 `blinky.c` 中的：

```c
#define BLINKY_STEP_PERIOD_MS (250UL)
```

例如，每一路点亮 500 ms：

```c
#define BLINKY_STEP_PERIOD_MS (500UL)
```

每一路点亮 100 ms：

```c
#define BLINKY_STEP_PERIOD_MS (100UL)
```

延时最终通过以下代码转换为 FreeRTOS Tick：

```c
vTaskDelayUntil(
    &next_wake_time,
    pdMS_TO_TICKS(BLINKY_STEP_PERIOD_MS));
```

使用 `vTaskDelayUntil()` 可以按照绝对唤醒时间运行，减少普通相对延时造成的周期漂移。

## 7. 修改 LED 切换顺序

当前代码依赖 `LED_Device_e` 枚举顺序自动递增：

```c
++active_led;

if (active_led >= LED_DEVICE_COUNT) {
    active_led = LED_DEVICE_STATUS;
}
```

如果需要自定义顺序，可以创建顺序表：

```c
static const LED_Device_e blink_order[] = {
    LED_DEVICE_RGB_BLUE,
    LED_DEVICE_RGB_GREEN,
    LED_DEVICE_RGB_RED,
    LED_DEVICE_STATUS
};
```

然后使用数组下标控制：

```c
size_t active_index = 0U;

for (;;) {
    LED_Device_e active_led = blink_order[active_index];

    (void)LEDOn(leds[active_led]);
    vTaskDelay(pdMS_TO_TICKS(BLINKY_STEP_PERIOD_MS));
    (void)LEDOff(leds[active_led]);

    ++active_index;
    if (active_index >=
        (sizeof(blink_order) / sizeof(blink_order[0]))) {
        active_index = 0U;
    }
}
```

## 8. 同时点亮多个 RGB 通道

同时点亮 RGB 红色和绿色，可以得到混合颜色：

```c
(void)LEDOn(leds[LED_DEVICE_RGB_RED]);
(void)LEDOn(leds[LED_DEVICE_RGB_GREEN]);
```

关闭两个通道：

```c
(void)LEDOff(leds[LED_DEVICE_RGB_RED]);
(void)LEDOff(leds[LED_DEVICE_RGB_GREEN]);
```

常见组合如下：

| 红 | 绿 | 蓝 | 显示颜色 |
| --- | --- | --- | --- |
| 开 | 关 | 关 | 红色 |
| 关 | 开 | 关 | 绿色 |
| 关 | 关 | 开 | 蓝色 |
| 开 | 开 | 关 | 黄色 |
| 关 | 开 | 开 | 青色 |
| 开 | 关 | 开 | 紫色 |
| 开 | 开 | 开 | 白色 |

## 9. LED 模块接口

底层 LED 模块提供以下接口：

```c
LEDInstance *LEDRegister(LED_Device_e device);
bool LEDOn(LEDInstance *instance);
bool LEDOff(LEDInstance *instance);
bool LEDToggle(LEDInstance *instance);
```

示例：

```c
LEDInstance *status_led = LEDRegister(LED_DEVICE_STATUS);

if (status_led != NULL) {
    (void)LEDOn(status_led);
    (void)LEDOff(status_led);
    (void)LEDToggle(status_led);
}
```

`LEDRegister()` 返回的是不透明实例。应用层无需知道 LED 使用哪个 GPIO，也不应该直接操作 `DL_GPIO_*` 接口。

## 10. 任务参数

当前 Blinky 任务使用以下配置：

```c
#define BLINKY_TASK_PRIORITY   (tskIDLE_PRIORITY + 1U)
#define BLINKY_TASK_STACK_SIZE (configMINIMAL_STACK_SIZE)
```

- 任务优先级比 FreeRTOS 空闲任务高 1。
- 任务栈使用项目配置的最小任务栈。
- Blinky 任务不接收外部参数。

## 11. 使用注意事项

1. 必须先执行 `BSPInit()`，再调用 `BlinkyInit()`。
2. `BlinkyInit()` 应在 `vTaskStartScheduler()` 之前调用。
3. 不要重复创建多个 Blinky 任务，否则多个任务会同时操作相同 LED。
4. 如果其他任务也要控制这些 LED，需要使用互斥锁或统一的 LED 控制任务，避免状态相互覆盖。
5. 独立状态灯和 RGB LED 的有效电平不同，应使用 `LEDOn()`、`LEDOff()`，不要在应用层直接写 GPIO 电平。
6. Blinky Module 默认不由顶层 Application 启动，只有调用 `BlinkyInit()` 才会运行。

## 12. 常见问题排查

### LED 完全不亮

依次检查：

1. 是否确实调用了 `BlinkyInit()`。
2. `BlinkyInit()` 是否位于 `BSPInit()` 之后。
3. 工程是否重新编译并烧录了最新固件。
4. 是否能进入 `BlinkyInit()` 和 `BlinkyTask()` 断点。
5. `LEDRegister()` 或 `LEDOff()` 是否返回失败。
