/**
 * @file wwdt_calc.h
 * @brief MSPM0 WWDT 分频/周期换算（纯整数，无 DriverLib 依赖，主机测试直接 include）。
 *
 * WWDT 时钟 = LFCLK（32.768 kHz）/ div，div = 1..8；计数周期只能取 2^6/8/10/12/15/18/21/25 拍
 * （MSPM0 G 系列 TRM WWDT 章 / SDK dl_wwdt.h 的 DL_WWDT_TIMER_PERIOD_*_BITS）。
 * 档位很粗：取“≥ 要求超时”里最短的一档（不会比要求的更容易咬），实际超时写回 *actual_ms。
 */
#ifndef WWDT_CALC_H
#define WWDT_CALC_H
#include <stdint.h>

static const uint8_t WWDT_PER_BITS[8] = { 6u, 8u, 10u, 12u, 15u, 18u, 21u, 25u };

/** 成功返回 1：*div = 分频 1..8，*per = WWDT_PER_BITS 下标 0..7；timeout 为 0 或超上限返回 0。 */
static inline int wwdt_calc(uint32_t timeout_ms, uint32_t lfclk_hz, uint8_t *div, uint8_t *per, uint32_t *actual_ms)
{
    uint64_t best = 0u;
    if (timeout_ms == 0u || lfclk_hz == 0u) return 0;
    for (uint8_t p = 0u; p < 8u; p++)
        for (uint8_t d = 1u; d <= 8u; d++) {
            uint64_t ms = ((uint64_t)d << WWDT_PER_BITS[p]) * 1000u / lfclk_hz;   /* 向下取整：报的实际值不夸大 */
            if (ms >= timeout_ms && (best == 0u || ms < best)) { best = ms; *div = d; *per = p; }
        }
    if (best == 0u || best > 0xFFFFFFFFu) return 0;
    *actual_ms = (uint32_t)best;
    return 1;
}
#endif
