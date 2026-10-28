/**
 * @file spsc.h
 * @brief 单生产者单消费者无锁环形队列（定长元素，带时间戳的采样最常用）。
 *
 * 典型用法：串口/视觉 ISR 里 spsc_push 一个 {t_ms, x, flags} 样本，主循环 spsc_pop。
 * 只有生产者写 head、只有消费者写 tail，单核下无需关中断。
 * 容量必须是 2 的幂，可用元素数 = 容量（head/tail 为自由增长的 32 位计数）。
 * 设计参考：P2 工程的时间戳采样队列；Linux kfifo（include/linux/kfifo.h）的“自由计数+掩码”做法。
 * 版本：SPSC_VERSION
 */
#ifndef SPSC_H
#define SPSC_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#define SPSC_VERSION "1.0.0"

typedef struct {
    uint8_t *buf;               /**< 容量 × 元素大小 的存储区（调用者提供） */
    uint16_t elem_size;
    uint16_t cap;               /**< 2 的幂 */
    volatile uint32_t head;     /**< 已写入总数（生产者写） */
    volatile uint32_t tail;     /**< 已读出总数（消费者写） */
    volatile uint32_t dropped;  /**< 满时丢弃的个数（生产者写） */
} spsc_t;

/** cap 不是 2 的幂、为 0、空指针 → DZ_EINVAL。 */
dz_err_t spsc_init(spsc_t *q, void *storage, uint16_t elem_size, uint16_t cap);
/** 满则丢弃新元素并计数，返回 DZ_EBUSY。[ISR-safe，仅生产者] */
dz_err_t spsc_push(spsc_t *q, const void *elem);
/** 空返回 false。[仅消费者] */
bool spsc_pop(spsc_t *q, void *elem);
/** 只取最新一个并丢弃更旧的（控制环只关心最新样本时用）。空返回 false。[仅消费者] */
bool spsc_pop_latest(spsc_t *q, void *elem);
uint32_t spsc_count(const spsc_t *q);
dz_err_t spsc_selftest(void);
#endif
