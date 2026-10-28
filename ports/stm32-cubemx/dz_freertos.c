/* FreeRTOS 小工具实现，见 dz_freertos.h。只在 BOARD_RTOS=freertos 时编译（Makefile）。【未测】上板。 */
#include "dz_freertos.h"
#include "FreeRTOS.h"
#include "task.h"
#include "main.h"          /* CMSIS 设备头：DWT / CoreDebug */
#include "pal.h"
#include "rtosmon.h"
#include <string.h>

#ifndef DZ_RTOS_MAX_TASKS
#define DZ_RTOS_MAX_TASKS 16u
#endif
#ifndef configIDLE_TASK_NAME
#define configIDLE_TASK_NAME "IDLE"
#endif

void dz_rtos_periodic(dz_rtos_task_t *t)
{
    if (!t || !t->step) return;
    TickType_t period = pdMS_TO_TICKS(t->period_ms);
    if (period == 0u) period = 1u;   /* 周期小于一个节拍：按一个节拍跑 */
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        uint32_t t0 = pal_micros();
        t->step(t->ctx, pal_millis());
        uint32_t dt = pal_micros() - t0;
        if (dt > t->max_exec_us) t->max_exec_us = dt;
        t->runs++;
        /* FreeRTOS ≥10.4 的 xTaskDelayUntil 返回 pdFALSE 表示已经错过了唤醒点；旧版用 vTaskDelayUntil 自己判断 */
        TickType_t now = xTaskGetTickCount();
        if ((TickType_t)(now - wake) >= period) { t->overruns++; wake = now; }   /* 超时：重新对齐，不连环补跑 */
        vTaskDelayUntil(&wake, period);
    }
}

#if configUSE_TRACE_FACILITY == 1
static TaskStatus_t s_ts[DZ_RTOS_MAX_TASKS];
#endif

void dz_rtos_monitor_poll(void)
{
#if configUSE_TRACE_FACILITY == 1
    static uint32_t last;
    uint32_t now = pal_millis();
    if (now - last < 500u) return;
    last = now;
    uint32_t total = 0;
    UBaseType_t n = uxTaskGetSystemState(s_ts, DZ_RTOS_MAX_TASKS, &total);   /* 任务数超过数组 → 返回 0 */
    if (n == 0u) return;
    rtosmon_begin_stack(&g_rtosmon);
    uint32_t idle = 0;
    for (UBaseType_t i = 0; i < n; i++) {
        rtosmon_feed_stack(&g_rtosmon, s_ts[i].pcTaskName, (uint32_t)s_ts[i].usStackHighWaterMark);
#if configGENERATE_RUN_TIME_STATS == 1
        if (strcmp(s_ts[i].pcTaskName, configIDLE_TASK_NAME) == 0) idle = (uint32_t)s_ts[i].ulRunTimeCounter;
#endif
    }
    rtosmon_end_stack(&g_rtosmon);
#if configGENERATE_RUN_TIME_STATS == 1
    rtosmon_feed_cpu(&g_rtosmon, idle, total);
#else
    (void)idle;
#endif
#endif
}

/* DZ-REG-OK: HAL 没有 DWT 周期计数器的接口，运行时统计只能直接读写 CoreDebug/DWT */
void configureTimerForRunTimeStats(void)
{
    CoreDebug->DEMCR |= /* DZ-REG-OK: 同上 */ CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0u;                            /* DZ-REG-OK: 同上 */
    DWT->CTRL |= /* DZ-REG-OK: 同上 */ DWT_CTRL_CYCCNTENA_Msk;
}
/* DZ-REG-OK: 同上 */
unsigned long getRunTimeCounterValue(void) { return DWT->CYCCNT; }
