/**
 * @file capfreq.h
 * @brief 输入捕获测频 / 占空比：喂边沿时间戳（定时器计数），按 N 个整周期平均出频率（毫赫兹）和占空比。纯 C。
 *
 *   多周期平均：f = timer_hz · N / (t_N − t_0)，比单周期倒数准 N 倍（计数量化误差 ±1 tick 摊到 N 个周期）。
 *   计数回绕：wrap = 计数器模（16 位定时器填 65536，32 位填 0）；单个间隔必须小于一圈，
 *   低频信号请把溢出次数并进高位、喂扩展后的 32 位计数（wrap = 0）。
 *
 * 思路参考：LP-MSPM0G3507_freertos_firework@ede35a2 modules/capture/capture.h（周期计数 → 毫赫兹、快照序号）。代码自写。
 * 版本：CAPFREQ_VERSION
 */
#ifndef CAPFREQ_H
#define CAPFREQ_H

#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"

#define CAPFREQ_VERSION "1.0.0"

typedef struct {
    uint32_t timer_hz;     /**< 捕获定时器计数频率，> 0 */
    uint32_t wrap;         /**< 计数器模，0 = 2^32 */
    uint8_t  periods;      /**< 平均的整周期数 N，1..32 */
    uint32_t timeout_ms;   /**< 超过这么久没有边沿 → 无信号 */
} capfreq_cfg_t;

typedef struct {
    capfreq_cfg_t c;
    uint32_t last_rise, last_edge_ms;
    uint64_t period_sum, high_sum;
    uint8_t  count;          /**< 已累计整周期数 */
    bool     have_rise, high_valid;
    uint32_t freq_mhz;
    float    duty;           /**< 0..1；只喂上升沿时为 NAN */
    uint32_t seq;            /**< 每出一个新结果 +1 */
} capfreq_t;

dz_err_t capfreq_init(capfreq_t *c, const capfreq_cfg_t *cfg);
/** 喂一个边沿：tick = 捕获值，rising = 上升沿，now_ms = 当前毫秒（判超时）。 */
void     capfreq_edge(capfreq_t *c, uint32_t tick, bool rising, uint32_t now_ms);
/** 读结果：无信号（超时或还没凑够 N 个周期）返回 false。 */
bool     capfreq_read(const capfreq_t *c, uint32_t now_ms, uint32_t *freq_mhz, float *duty);
void     capfreq_reset(capfreq_t *c);

dz_err_t capfreq_selftest(void);

#endif /* CAPFREQ_H */
