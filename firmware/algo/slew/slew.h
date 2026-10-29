/**
 * @file slew.h
 * @brief 不对称变化率限制（斜坡）。纯 C，无硬件依赖。
 *
 * 场景：小车"起步要慢（不打滑、不翻）、刹车要快（不撞）"；舵机/云台"往外打慢、回中快"。
 * PID 自带的 out_rate_max 只有一个对称速率，这里把上升和下降分开。
 *
 *   SLEW_BY_DIR  rise = 往正方向变的速率上限，fall = 往负方向变的速率上限
 *   SLEW_BY_MAG  rise = 远离 0 的速率上限（加速），fall = 靠近 0 的速率上限（减速）；
 *                跨零时先按 fall 走到 0，本拍剩余时间再按 rise 往另一侧走
 *   速率单位：输出单位/秒；0 = 不限。
 *
 * 用法：PID 的 out_rate_max 设 0，把 pid_update 的输出再过一次 slew_update。
 * 输出限幅（含不对称上下限）仍由 PID 的 out_min/out_max 负责。
 *
 * 版本：SLEW_VERSION
 */
#ifndef SLEW_H
#define SLEW_H

#include <stdbool.h>
#include "dz_err.h"

#define SLEW_VERSION "1.0.0"

typedef enum { SLEW_BY_DIR = 0, SLEW_BY_MAG = 1 } slew_mode_t;

typedef struct {
    float rise_per_s;     /**< >= 0，0 = 不限 */
    float fall_per_s;     /**< >= 0，0 = 不限 */
    slew_mode_t mode;
} slew_cfg_t;

typedef struct {
    slew_cfg_t cfg;
    float y;
    bool  ready;
} slew_t;

dz_err_t slew_init(slew_t *s, const slew_cfg_t *cfg, float y0);
/** 以 dt_s 为周期调用，返回限速后的输出。非法输入（NaN/dt<=0）保持上次输出。 */
float    slew_update(slew_t *s, float target, float dt_s);
/** 急停 / 手动切换时直接把输出设成 y（不受速率限制）。 */
void     slew_reset(slew_t *s, float y);
dz_err_t slew_selftest(void);

#endif
