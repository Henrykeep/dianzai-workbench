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

#define ATTITUDE_VERSION "1.1.0"

typedef struct {
    float tau_s;      /**< 互补滤波时间常数：越大越信陀螺。0.5 s 是常用起点 */
    float acc_gate;   /**< |a|/g 的允许偏差，0.15 = ±15 % */
    float roll, pitch;   /**< rad */
    bool inited;
} attitude_t;

dz_err_t attitude_init(attitude_t *a, float tau_s, float acc_gate);
/** acc：m/s²，gyr：rad/s，dt：s。第一次调用直接用加速度定初值。 */
dz_err_t attitude_update(attitude_t *a, const float acc[3], const float gyr[3], float dt);
/**
 * 去重力（1.1.0）：用当前 roll/pitch 算本体系重力分量 g·(−sinθ, sinφ·cosθ, cosφ·cosθ)，从 acc 里减掉，得到运动加速度（m/s²，本体系）。
 * 与 dzimu_linear_acc 同一公式（主控直接读 MPU6050/BMI088 时用这个）。还没 inited 返回 false，out = acc 原样。
 * 注意：持续加速时互补滤波的姿态本身会被拉偏（acc_gate 只挡大冲击），去重力结果只适合短时、小加速度。
 */
bool attitude_linear_acc(const attitude_t *a, const float acc[3], float out[3]);
dz_err_t attitude_selftest(void);
#endif
