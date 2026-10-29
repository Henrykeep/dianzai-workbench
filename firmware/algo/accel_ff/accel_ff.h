/**
 * @file accel_ff.h
 * @brief 加速度前馈（倾角补偿）。纯 C，无硬件依赖。
 *
 * 场景：载体（小车/平台）加速时，把测得的线加速度换算成"抵消惯性力所需的倾角"叠加到反馈输出上，
 * 例如球杆/平衡板在移动底盘上、云台随车加速。小角近似 θ ≈ a/g。
 *
 *   out = clamp( sign(a)·(|a|-dead) / g · 57.2958 · gain , ±max_deg )
 *   - gain == 0          → 0（关闭）
 *   - !valid / NaN / |a| > fail → 0（失效保护：退回纯反馈，不会锁死）
 *   - |a| < dead         → 0（死区；边沿连续不跳变）
 *
 * 加速度来源（编码器差分 / IMU / 超时判断）由调用方决定并传 valid，本模块不关心。
 * 版本：ACCEL_FF_VERSION
 */
#ifndef ACCEL_FF_H
#define ACCEL_FF_H

#include <stdbool.h>
#include "dz_err.h"

#define ACCEL_FF_VERSION "1.0.0"

typedef struct {
    float gain;          /**< 0 = 关闭 */
    float dead_mps2;     /**< >= 0 */
    float fail_mps2;     /**< > 0，超过视为读数异常 */
    float max_deg;       /**< >= 0，输出限幅 */
} accel_ff_cfg_t;

/** 返回前馈角（°）。valid=false 时返回 0。 */
float    accel_ff_deg(const accel_ff_cfg_t *cfg, float accel_mps2, bool valid);
dz_err_t accel_ff_selftest(void);

#endif
