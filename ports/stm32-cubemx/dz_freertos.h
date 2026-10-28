/**
 * @file dz_freertos.h
 * @brief FreeRTOS 工程的小工具（仅 config_source.rtos: freertos 的板子编进来）：周期任务模板 + 运行监测喂数。
 *
 *  1) 周期任务：在 CubeMX 里建任务（入口函数名随意，如 StartCtrlTask），入口里只写一行
 *         dz_rtos_periodic(&my_task);            // 永不返回；节拍用 vTaskDelayUntil，不漂移
 *     模板见 freertos_task_template.c（复制到 Core/Src，或照抄到 freertos.c 的 USER CODE 区）。
 *  2) 运行监测：dz_cubemx_loop() 已自动调用 dz_rtos_monitor_poll()（内部 500 ms 一次），main.c 不用改
 *     → 写 g_rtosmon（firmware/framework/rtosmon），应用把 cpu_pm / stk_min_w 放进遥测。
 *  3) CPU 负载需要运行时统计：CubeMX → FREERTOS → Config parameters → GENERATE_RUN_TIME_STATS = Enabled。
 *     CubeMX 会要求实现 configureTimerForRunTimeStats() / getRunTimeCounterValue()，本文件已用 DWT 周期计数器实现。
 *     没开 → cpu_pm = 0xFFFF（无数据），栈余量照常有（需要 USE_TRACE_FACILITY = Enabled，CubeMX 默认开）。
 * 【未测】上板。
 */
#ifndef DZ_FREERTOS_H
#define DZ_FREERTOS_H
#include <stdint.h>

typedef struct {
    const char *name;               /**< 仅说明用 */
    uint32_t period_ms;             /**< 周期，≥1 */
    void (*step)(void *ctx, uint32_t now_ms);
    void *ctx;
    volatile uint32_t runs, overruns; /**< overruns：本次 step 超过一个周期（节拍被重新对齐） */
    volatile uint32_t max_exec_us;  /**< 单次 step 最长耗时 */
} dz_rtos_task_t;

/** 周期任务主体：永不返回。step 为空则直接返回（防误用）。 */
void dz_rtos_periodic(dz_rtos_task_t *t);
/** 采样所有任务栈高水位 + CPU 负载到 g_rtosmon；内部限速 500 ms，可以每圈都调。 */
void dz_rtos_monitor_poll(void);

/* CubeMX GENERATE_RUN_TIME_STATS 要求的两个函数（DWT->CYCCNT，CPU 时钟计数） */
void configureTimerForRunTimeStats(void);
unsigned long getRunTimeCounterValue(void);
#endif
