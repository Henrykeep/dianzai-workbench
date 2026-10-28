/**
 * @file abobs.h
 * @brief α-β 观测器（常速度模型），从带噪声、可能断续的位置测量估计位置和速度。纯 C。
 *
 *   预测  x̂⁻ = x̂ + v̂·dt
 *   更新  r = z − x̂⁻;  x̂ = x̂⁻ + α·r;  v̂ = v̂ + (β/dt)·r
 *   α 越大越信测量（跟得快、噪声大），β 决定速度响应。常用起点 α=0.5、β=0.1。
 *   没有新测量时只调用 abobs_predict（视觉 HELD 状态下外推）；超过 max_predict_s 后速度清零，防止外推飞走。
 *   残差 |r| > gate 时判为野值，丢弃这次测量（gate=0 表示不设门限）。
 *
 * 版本：ABOBS_VERSION
 */
#ifndef ABOBS_H
#define ABOBS_H

#include <stdbool.h>
#include "dz_err.h"

#define ABOBS_VERSION "1.0.0"

typedef struct {
    float alpha;          /**< (0,1] */
    float beta;           /**< [0,2)，且要求 β < 4−2α 才稳定 */
    float gate;           /**< 野值门限（测量单位），0 = 不用 */
    float max_predict_s;  /**< 连续外推上限（秒），0 = 不限 */
} abobs_cfg_t;

typedef struct {
    abobs_cfg_t cfg;
    float x, v;
    float coast_s;
    bool  primed;
    unsigned rejected;
} abobs_t;

dz_err_t abobs_init(abobs_t *o, const abobs_cfg_t *cfg);
/** 有测量：先预测 dt 再校正。返回 false 表示这次测量被门限丢弃（仍完成了预测）。 */
bool     abobs_update(abobs_t *o, float z, float dt_s);
/** 没有测量：只外推 dt。 */
void     abobs_predict(abobs_t *o, float dt_s);
void     abobs_reset(abobs_t *o, float x0);
dz_err_t abobs_selftest(void);

#endif
