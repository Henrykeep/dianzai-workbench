/**
 * @file dz_wrap.h
 * @brief 硬件计数器回绕差分（16/32 位）。MSPM0 TIMG8 QEI、STM32 16 位 TIM 编码器模式都只有 16 位：
 *        必须先按 uint16 相减再转 int16，不能把原始计数直接转 int32（会在 65535→0 时跳一大步）。
 *        前提：两次读之间真实增量 |Δ| < 32768。
 */
#ifndef DZ_WRAP_H
#define DZ_WRAP_H
#include <stdint.h>

static inline int32_t dz_wrap16_delta(uint16_t now, uint16_t last) { return (int32_t)(int16_t)(uint16_t)(now - last); }
static inline int32_t dz_wrap32_delta(uint32_t now, uint32_t last) { return (int32_t)(now - last); }

#endif
