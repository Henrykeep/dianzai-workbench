/**
 * @file drive_plan.h
 * @brief 纯逻辑子系统：把上位机指令（线速度 v、角速度 w）变成左右轮目标转速，带斜坡限幅和指令超时急停。
 *        不碰硬件（只读写 car_state_t），因此可以在电脑上喂模拟数据单独测。
 */
#ifndef DRIVE_PLAN_H
#define DRIVE_PLAN_H
#include <stdbool.h>
#include <stdint.h>
#include "subsys.h"

typedef struct {
    /* 输入（io 胶水写） */
    float    cmd_v_mps, cmd_w_rps;     /**< 线速度 m/s、角速度 rad/s */
    uint32_t cmd_ms;                    /**< 最近一次收到指令的时刻 */
    /* 输出（drive_plan 写） */
    float    sp_a_rps, sp_b_rps;        /**< 左(A)/右(B) 轮目标转速 转/秒 */
    bool     timed_out;
} car_state_t;

typedef struct {
    float wheel_diam_m;      /**< 轮径 */
    float track_m;           /**< 轮距 */
    float max_rps;           /**< 轮速上限 */
    float accel_rps2;        /**< 轮速斜坡 转/秒² */
    uint32_t cmd_timeout_ms; /**< 超过这么久没收到指令就停车（防上位机断线跑飞） */
} drive_params_t;

extern const subsys_t g_drive_plan;
#endif
