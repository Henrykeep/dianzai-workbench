/* Blinky 示例使用静态 FreeRTOS 任务依次轮转四路板载 LED。 */
#include "modules/led/blinky.h"

#include <stddef.h>

#include "FreeRTOS.h"
#include "task.h"

#include "modules/led/led.h"

#define BLINKY_TASK_PRIORITY    (tskIDLE_PRIORITY + 1U)
#define BLINKY_TASK_STACK_SIZE  (configMINIMAL_STACK_SIZE)
#define BLINKY_STEP_PERIOD_MS   (250UL)

/* 保存四路板载 LED 的不透明实例，数组下标与逻辑 LED 枚举一致。 */
static LEDInstance *leds[LED_DEVICE_COUNT];
static bool blinky_task_created;
static StaticTask_t blinky_task_control;
static StackType_t blinky_task_stack[BLINKY_TASK_STACK_SIZE];

static void BlinkyTask(void *argument);

bool BlinkyInit(void)
{
    LED_Device_e device;

    if (blinky_task_created) {
        return true;
    }

    /* 启动调度器前注册全部板载 LED，并统一置为熄灭状态。 */
    for (device = LED_DEVICE_STATUS; device < LED_DEVICE_COUNT; ++device) {
        leds[device] = LEDRegister(device);
        if ((leds[device] == NULL) || !LEDOff(leds[device])) {
            return false;
        }
    }

    if (xTaskCreateStatic(BlinkyTask, "Blinky",
            BLINKY_TASK_STACK_SIZE, NULL, BLINKY_TASK_PRIORITY,
            blinky_task_stack, &blinky_task_control) == NULL) {
        return false;
    }

    blinky_task_created = true;
    return true;
}

static void BlinkyTask(void *argument)
{
    /* 记录绝对唤醒时刻，避免普通延时造成周期逐步漂移。 */
    TickType_t next_wake_time = xTaskGetTickCount();
    LED_Device_e active_led   = LED_DEVICE_STATUS;

    /* 当前任务无需外部参数，显式转换用于消除未使用参数告警。 */
    (void) argument;

    /* 每轮只驱动一路 LED，等待固定时间后再切换到下一路。 */
    for (;;) {
        /* 每一步只点亮一路：独立红灯，然后依次显示 RGB 红、绿、蓝。 */
        (void) LEDOn(leds[active_led]);
        /* 固定延时期间当前任务阻塞，其他同优先级或更高优先级任务可运行。 */
        vTaskDelayUntil(
            &next_wake_time, pdMS_TO_TICKS(BLINKY_STEP_PERIOD_MS));
        (void) LEDOff(leds[active_led]);

        /* 切换到下一路 LED，最后一路完成后重新从状态灯开始。 */
        ++active_led;
        if (active_led >= LED_DEVICE_COUNT) {
            active_led = LED_DEVICE_STATUS;
        }
    }
}
