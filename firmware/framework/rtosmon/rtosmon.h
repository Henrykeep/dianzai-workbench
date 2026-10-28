/**
 * @file rtosmon.h
 * @brief RTOS 运行监测（纯逻辑，不依赖任何 RTOS 头文件）：CPU 负载 + 各任务栈余量（高水位）。
 *
 * 数据由移植层喂进来（FreeRTOS：ports/stm32-cubemx/dz_freertos.c 用 uxTaskGetSystemState），
 * 应用层只读 g_rtosmon，遥测里发 cpu_pm / stk_min_w。裸机板没人喂 → 读到 RTOSMON_NA，上位机显示“无”。
 *  - CPU 负载 = 1 - Δidle/Δtotal（两次采样之差，32 位计数回绕安全），单位千分比。
 *  - 栈余量 = 每个任务历史最小剩余字数（FreeRTOS 高水位本身就是“历史最小”），取所有任务的最小值并记下是谁。
 * 版本：RTOSMON_VERSION
 */
#ifndef RTOSMON_H
#define RTOSMON_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#define RTOSMON_VERSION "1.0.0"
#define RTOSMON_NA 0xFFFFu          /**< 没有数据（裸机，或 RTOS 没开运行时统计） */
#define RTOSMON_NAME_LEN 16u

typedef struct {
    uint32_t last_idle, last_total;
    uint16_t cpu_pm;                /**< 0..1000，或 RTOSMON_NA */
    uint16_t stk_min_w;             /**< 所有任务里最小的栈余量（字 = 4 字节），或 RTOSMON_NA */
    uint16_t scan_min_w;            /**< 本轮扫描中的最小值（begin..end 之间） */
    char worst[RTOSMON_NAME_LEN];   /**< 栈余量最小的任务名 */
    char scan_worst[RTOSMON_NAME_LEN];
    uint8_t n_tasks, scan_n;
    bool have_cpu;
    uint32_t samples;
} rtosmon_t;

/** 应用读、移植层写（同一任务里读写，或写方关调度后整体更新）。 */
extern rtosmon_t g_rtosmon;

void rtosmon_init(rtosmon_t *m);
/** 喂一次累计计数：idle = 空闲任务累计运行时间，total = 总运行时间（同一时钟）。第一次只记基准。 */
void rtosmon_feed_cpu(rtosmon_t *m, uint32_t idle, uint32_t total);
/** 一轮栈扫描：begin → 每个任务 feed_stack → end（end 时才更新 stk_min_w，避免读到半轮结果）。 */
void rtosmon_begin_stack(rtosmon_t *m);
void rtosmon_feed_stack(rtosmon_t *m, const char *name, uint32_t free_words);
void rtosmon_end_stack(rtosmon_t *m);
uint16_t rtosmon_cpu_permille(const rtosmon_t *m);
uint16_t rtosmon_stack_min_words(const rtosmon_t *m);
/** 栈余量低于 thresh_words（建议 32 字 = 128 字节）→ true。没数据 → false。 */
bool rtosmon_stack_low(const rtosmon_t *m, uint16_t thresh_words);
dz_err_t rtosmon_selftest(void);
#endif
