/**
 * @file attitude.h
 * @brief 互补滤波求横滚/俯仰角：短时间信陀螺积分，长时间用加速度的重力方向修正漂移。
 *
 * 只算 roll 和 pitch，不算 yaw（没有磁力计时 yaw 必然漂移）。
 * 当 |a| 偏离 1 g 超过 acc_gate（比如急加速或碰撞）时，这一拍不做加速度修正，只积分陀螺。
 * 版本：ATTITUDE_VERSION
 */
#ifndef ATTITUDE_H
#define ATTITUDE_H
#include <stdbool.h>
#include "dz_err.h"

#define ATTITUDE_VERSION "1.0.0"

typedef struct {
    float tau_s;      /**< 互补滤波时间常数：越大越信陀螺。0.5 s 是常用起点 */
    float acc_gate;   /**< |a|/g 的允许偏差，0.15 = ±15 % */
    float roll, pitch;   /**< rad */
    bool inited;
} attitude_t;

dz_err_t attitude_init(attitude_t *a, float tau_s, float acc_gate);
/** acc：m/s²，gyr：rad/s，dt：s。第一次调用直接用加速度定初值。 */
dz_err_t attitude_update(attitude_t *a, const float acc[3], const float gyr[3], float dt);
dz_err_t attitude_selftest(void);
#endif
