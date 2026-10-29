/**
 * @file iwdg_calc.h
 * @brief STM32 IWDG 分频/重装值换算（纯整数，无 HAL 依赖，主机测试直接 include）。
 *
 * IWDG：LSI 时钟 / (4 << PR)，PR = 0..6（/4../256），RLR 12 位（1..4095）。
 * 取能放下 timeout 的最小分频（分辨率最高）。所有 STM32 系列 IWDG 寄存器相同，LSI 标称值不同：
 * F1 40 kHz，F4/F7/G4/H7 等 32 kHz（RM0008 / RM0090）。
 */
#ifndef IWDG_CALC_H
#define IWDG_CALC_H
#include <stdint.h>

/** 成功返回 1 并写出 pr/rlr；timeout 为 0 或超上限返回 0。 */
static inline int iwdg_calc(uint32_t timeout_ms, uint32_t lsi_hz, uint8_t *pr, uint16_t *rlr)
{
    if (timeout_ms == 0u || lsi_hz == 0u) return 0;
    for (uint8_t k = 0u; k <= 6u; k++) {
        uint32_t div = 4u << k;
        uint64_t ticks = ((uint64_t)timeout_ms * lsi_hz + (uint64_t)div * 1000u - 1u) / ((uint64_t)div * 1000u);
        if (ticks == 0u) ticks = 1u;
        if (ticks <= 4096u) { *pr = k; *rlr = (uint16_t)(ticks - 1u); return 1; }
    }
    return 0;
}
#endif
