/**
 * @file mtspeed.h
 * @brief 变周期 M/T 法测速（Ohmae M/T 的变周期形式）。纯 C，无硬件依赖。
 *
 * 为什么要它：低线数编码器 + 高频控制环时，固定窗口差分（M 法）每周期只有零点几个脉冲，
 * 速度只能在 0 和 1 脉冲/周期之间跳。T 法（测相邻脉冲间隔）低速准、高速差。
 * 变周期 M/T：本控制周期内到达的 m 个边沿，用"上一窗口最后一个边沿 → 本窗口最后一个边沿"的
 * 真实时间 T 去除，speed = m / T。高速时 T≈控制周期（等于 M 法），低速时 T 是整数个脉冲间隔（等于 T 法），
 * 误差只有一个时钟（1 µs），与速度无关。
 *
 * 用法：
 *   边沿中断：mtspeed_edge(&m, t_us, dir)   t_us 用 PAL 边沿回调给的时间戳，dir=+1/-1（看另一相电平）
 *   控制周期：mtspeed_poll(&m, now_us) 后读 mtspeed_rps(&m)
 *   只喂同一种边沿（例如 A 相上升沿）：正交编码器四个边沿的间距不均匀（相位差不是正好 90°），
 *   混着喂会让 T 法那一段读数抖。counts_per_rev 填"每转喂进来的边沿数"。
 * 超时：timeout_us 内没有边沿 → 速度为 0。没有新边沿但未超时时，速度取 min(上次, 1/(now−最后边沿))，
 *   即"不可能比这更快"，减速时读数自然往下走，不会卡在旧值。
 * 中断并发：edge 在中断里改计数，poll 用版本号双读（单核 Cortex-M 上中断整段执行完，重读即可得到一致快照）。
 * 时间戳 32 位 µs 回绕（约 71 分钟）按无符号相减处理。
 *
 * 版本：MTSPEED_VERSION
 */
#ifndef MTSPEED_H
#define MTSPEED_H

#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"

#define MTSPEED_VERSION "1.0.0"

typedef struct {
    float    counts_per_rev;  /**< 每转喂进来的边沿数，> 0 */
    uint32_t timeout_us;      /**< 超过它没有边沿 → 0 速，> 0；例：最低关心转速下两个边沿间隔的 2 倍 */
} mtspeed_cfg_t;

typedef struct {
    mtspeed_cfg_t cfg;
    /* 中断写 */
    volatile uint32_t gen;        /**< 奇数 = 中断正在写 */
    volatile int32_t  count;      /**< 累计带符号边沿数 */
    volatile uint32_t t_last;     /**< 最近边沿时间戳 */
    volatile bool     any;
    /* poll 用 */
    int32_t  count_ref;
    uint32_t t_ref;
    bool     have_ref;
    bool     stopped;     /**< 超时后：下一个新边沿只当起点（不用停车前的旧边沿算 T） */
    float    rps;
    bool     ready;
} mtspeed_t;

dz_err_t mtspeed_init(mtspeed_t *m, const mtspeed_cfg_t *cfg);
/** 边沿中断里调用。[ISR-safe] dir：+1 正转，-1 反转。 */
void     mtspeed_edge(mtspeed_t *m, uint32_t t_us, int8_t dir);
/** 控制周期里调用，更新速度。 */
void     mtspeed_poll(mtspeed_t *m, uint32_t now_us);
float    mtspeed_rps(const mtspeed_t *m);
dz_err_t mtspeed_selftest(void);

#endif
