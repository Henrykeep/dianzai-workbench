/**
 * @file dzrtt.h
 * @brief 极简 SEGGER RTT 兼容控制块：1 路上行 + 1 路下行（通道 0），让 LINK 走调试探针、不占串口。
 *
 * 内存布局与 SEGGER RTT 一致（控制块 ID "SEGGER RTT"），pyOCD / J-Link / OpenOCD 的 RTT 都能找到。
 * 不依赖 SEGGER 源码；非阻塞：上行缓冲满了就丢这一段（返回 DZ_EBUSY），与串口 EBUSY 丢帧语义一致。
 * 只允许单个写者（一个上下文调 dzrtt_write），单个读者（一个上下文调 dzrtt_read）。
 */
#ifndef DZRTT_H
#define DZRTT_H

#include <stdint.h>
#include "dz_err.h"

#ifndef DZRTT_UP_SIZE
#define DZRTT_UP_SIZE   1024u   /**< 上行（板→PC）缓冲字节数；遥测 100 Hz × ~40 B 约 4 KB/s，探针轮询 ≥10 Hz 够用 */
#endif
#ifndef DZRTT_DOWN_SIZE
#define DZRTT_DOWN_SIZE 256u    /**< 下行（PC→板）缓冲字节数 */
#endif

typedef struct {
    const char *name;
    char *buf;
    uint32_t size;
    volatile uint32_t wr;
    volatile uint32_t rd;
    uint32_t flags;
} dzrtt_ring_t;

typedef struct {
    char id[16];
    int32_t max_up;
    int32_t max_down;
    dzrtt_ring_t up[1];
    dzrtt_ring_t down[1];
} dzrtt_cb_t;

extern dzrtt_cb_t g_dzrtt;                      /**< 控制块（探针在 RAM 里搜 ID 找到它） */

void dzrtt_init(void);                          /**< 可重复调用；第一次 write/read 也会自动调 */
dz_err_t dzrtt_write(const uint8_t *buf, uint16_t len);     /**< 全写进去或一字节都不写（不拆帧）；满 → DZ_EBUSY */
dz_err_t dzrtt_read(uint8_t *buf, uint16_t max, uint16_t *got);
int dzrtt_selftest(void);

#endif
