/**
 * @file link_io.h
 * @brief LINK 收发的唯一开关：默认串口 RES_UART_LINK；`make LINK=rtt` 时走调试探针 RTT 通道 0（dzrtt）。
 */
#ifndef LINK_IO_H
#define LINK_IO_H

#include <stdbool.h>
#include "pal.h"
#include "board_gen.h"

#if defined(DZ_LINK_RTT) && DZ_LINK_RTT
#include "dzrtt.h"
static inline dz_err_t link_write(const uint8_t *b, uint16_t n) { return dzrtt_write(b, n); }
static inline dz_err_t link_read(uint8_t *b, uint16_t max, uint16_t *got) { return dzrtt_read(b, max, got); }
static inline dz_err_t link_tx_idle(bool *idle) { *idle = true; return DZ_OK; }
#else
static inline dz_err_t link_write(const uint8_t *b, uint16_t n) { return pal_uart_write(RES_UART_LINK, b, n); }
static inline dz_err_t link_read(uint8_t *b, uint16_t max, uint16_t *got) { return pal_uart_read(RES_UART_LINK, b, max, got); }
static inline dz_err_t link_tx_idle(bool *idle) { return pal_uart_tx_idle(RES_UART_LINK, idle); }
#endif

#endif
