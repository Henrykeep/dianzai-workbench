/**
 * @file encoder.h
 * @brief 编码器测速/测位置。依赖 pal.h（读计数）与 algo/lpf（速度滤波）。
 *
 * 版本：ENCODER_VERSION（与同目录 VERSION 文件一致）
 *
 * 用法：在固定周期（例如 1 kHz 控制中断）里调用 encoder_update()，
 * 再用 encoder_speed_rps() / encoder_position_rev() 读结果。
 *
 * 计数换算：counts_per_rev = 编码器线数 × 倍频(正交 4 倍频填 4) × 减速比。
 *   例：13 线霍尔、4 倍频、减速比 30 → 13*4*30 = 1560。
 *   ⚠ 以上为示例算式，请按你的电机铭牌/手册填写。
 */
#ifndef ENCODER_H
#define ENCODER_H

#include <stdbool.h>
#include <stdint.h>
#include "pal.h"
#include "lpf1.h"

#define ENCODER_VERSION "1.1.0"
#define ENCODER_WINDOW_MAX 32u

typedef struct {
    pal_id_t enc;            /**< 编码器逻辑 ID，例如 RES_ENCODER_MOTOR_A */
    float counts_per_rev;    /**< 输出轴每转计数，> 0 */
    float dt_s;              /**< encoder_update 的调用周期（秒），> 0 */
    float speed_lpf_hz;      /**< 速度低通截止频率；0 关闭 */
    bool  invert;            /**< 方向反了就置 true */
    uint8_t window_n;        /**< 测速窗口（周期数，1..ENCODER_WINDOW_MAX；0/1 = 单周期差分）。
                                  低 PPR + 高频控制时每周期只有零点几个脉冲，量化噪声极大：
                                  例 1 kHz、每周期 0.3 脉冲 → 单周期速度只能是 0 或 1 脉冲/ms。
                                  取 window_n=20 → 分辨率提高 20 倍，代价是约 window_n/2 个周期的延迟（M 法加长窗口；
                                  真 M/T 法要边沿时间戳捕获，PAL 暂无，未实现）。 */
} encoder_cfg_t;

typedef struct {
    encoder_cfg_t cfg;
    lpf1_t  lpf;
    int32_t last_count;
    int64_t total;           /**< 累计计数（64 位，长时间运行不溢出） */
    int32_t last_delta;
    float   speed_rps;
    int32_t win[ENCODER_WINDOW_MAX];
    int32_t win_sum;
    uint8_t win_i, win_fill;
    bool    use_lpf;
    bool    ready;
} encoder_t;

encoder_cfg_t encoder_cfg_default(void);

/** 校验配置，读取当前计数作为零点。 */
dz_err_t encoder_init(encoder_t *e, const encoder_cfg_t *cfg);

/** 以固定周期调用。[ISR-safe] */
dz_err_t encoder_update(encoder_t *e);

/** 输出轴转速（转/秒）。 */
float   encoder_speed_rps(const encoder_t *e);
/** 输出轴转速（转/分）。 */
float   encoder_speed_rpm(const encoder_t *e);
/** 输出轴累计转数（自 init 或 zero 起）。 */
float   encoder_position_rev(const encoder_t *e);
/** 累计原始计数。 */
int64_t encoder_count(const encoder_t *e);
/** 最近一个周期的计数增量（未滤波），用于诊断丢步/干扰。 */
int32_t encoder_last_delta(const encoder_t *e);
/** 位置清零（速度不变）。 */
void    encoder_zero(encoder_t *e);

/**
 * 静止自检：在电机不转的情况下调用，持续 duration_ms 采样，
 * 若累计计数变化超过 max_jitter_counts 返回 DZ_EFAIL（说明有干扰或机械在动）。
 */
dz_err_t encoder_selftest_still(encoder_t *e, uint32_t duration_ms, int32_t max_jitter_counts);

#endif /* ENCODER_H */
