/*
 * FreeRTOS 周期任务模板（复制到 Core/Src 并改名，或把内容抄进 CubeMX 生成的 freertos.c 的 USER CODE 区）。
 * 不在构建里编译（只是模板）。CubeMX 里建任务：Tasks and Queues → Add，Entry Function 填 StartCtrlTask，
 * Code Generation Option 选 As weak 或 As external，栈先给 256 字（1 KB），跑起来看遥测 stk_min_w 再收紧。
 *
 * 规则（与裸机版一致，见 docs/11-中断与实时.md）：
 *  - 控制环放高优先级周期任务；串口收发/遥测放普通优先级；不要在任务里 HAL_Delay（用 osDelay / vTaskDelayUntil）。
 *  - 任务间共享的数据：单写单读的标量可直接读写；结构体用 taskENTER_CRITICAL 或 spsc 队列。
 *  - 栈余量 < 32 字（128 字节）就加栈：遥测 stk_min_w、调试器 RTOS 视图都能看到。
 * 【未测】上板。
 */
#include "dz_freertos.h"

static void ctrl_step(void *ctx, uint32_t now_ms)
{
    (void)ctx; (void)now_ms;
    /* 在这里调控制环，例如 subsys_sched_poll(&sched, now_ms); */
}

static dz_rtos_task_t s_ctrl = { "ctrl", 5u, ctrl_step, 0, 0u, 0u, 0u };   /* 5 ms = 200 Hz */

void StartCtrlTask(void *argument)
{
    (void)argument;
    dz_rtos_periodic(&s_ctrl);   /* 永不返回 */
}
