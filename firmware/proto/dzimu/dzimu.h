/**
 * @file dzimu.h
 * @brief IMU 姿态模块 → 主控的数据帧（dzframe/1 DATA 通道 DZIMU_CH）。
 *
 * 用途：把一块独立的 IMU 板（例如 RoboMaster C 型板，跑 apps/imu_module）当“姿态模块”，经串口给主控发
 *       加速度 / 角速度 / 横滚俯仰。主控用 dzimu_decode 解出 dzimu_sample_t，喂给前馈或姿态环。
 * 负载（小端，37 字节）：
 *   u32 t_ms | f32 ax ay az (m/s²) | f32 gx gy gz (rad/s) | f32 roll pitch (deg) | u8 status
 *   status：bit0 加速度计正常 bit1 陀螺仪正常 bit2 姿态已收敛 bit3 零偏已标定 bit4 加速度计量程饱和
 * 坐标系：模块本体坐标（右手系，z 向上），装到车上的方向由主控侧参数决定（见 dzimu_axis）。
 * 版本：DZIMU_VERSION
 */
#ifndef DZIMU_H
#define DZIMU_H
#include <stdbool.h>
#include <stdint.h>
#include "dzframe.h"

#define DZIMU_VERSION "1.1.0"
#define DZIMU_CH 0x20u                /**< DATA 通道号（与视觉 1、遥测 2 等不冲突） */
#define DZIMU_SIZE 37u

#define DZIMU_ST_ACC_OK   0x01u
#define DZIMU_ST_GYR_OK   0x02u
#define DZIMU_ST_ATT_OK   0x04u
#define DZIMU_ST_BIAS_OK  0x08u
#define DZIMU_ST_ACC_SAT  0x10u

typedef struct {
    uint32_t t_ms;        /**< 模块本地时钟 */
    float acc[3];         /**< m/s²，静止时 |acc| ≈ 9.8（含重力） */
    float gyr[3];         /**< rad/s，已减零偏 */
    float roll_deg, pitch_deg;
    uint8_t status;
} dzimu_sample_t;

bool dzimu_encode(const dzimu_sample_t *s, uint8_t seq, dzframe_t *f);
bool dzimu_decode(const dzframe_t *f, dzimu_sample_t *out);   /**< 通道/长度不对或含 NaN 返回 false */

/** 取安装后的某根轴：axis 0..5 = +x -x +y -y +z -z（例如模块 y 轴朝车头 → 前向加速度用 axis=2）。越界返回 NAN。 */
float dzimu_axis(const float v[3], uint8_t axis);

/**
 * 去重力：用模块给出的 roll/pitch 估计本体系下的重力分量，从加速度里减掉，得到“运动加速度”（m/s²，模块本体坐标）。
 * 角度约定与 firmware/algo/attitude 一致：roll=atan2(ay,az)，pitch=atan2(-ax,√(ay²+az²))，静止时
 * acc ≈ g·[−sin p, sin r·cos p, cos r·cos p]。
 * 只有 status 含 DZIMU_ST_ATT_OK 时姿态才可信：否则返回 false，out 原样拷贝含重力的 acc（调用方自行决定是否使用）。
 * 误差：姿态误差 1° ≈ 0.17 m/s² 残余；剧烈加减速时互补滤波的姿态本身会被拉偏，仍有残余。
 */
#define DZIMU_G 9.80665f
bool dzimu_linear_acc(const dzimu_sample_t *s, float out[3]);

dz_err_t dzimu_selftest(void);
#endif
