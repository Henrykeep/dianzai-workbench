/**
 * @file tb6612.h
 * @brief 双路 TB6612 电机速度、停止模式、待机和状态快照接口。
 */
#ifndef TB6612_H
#define TB6612_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    /** TB6612 A 通道。 */
    TB6612_MOTOR_A = 0,
    /** TB6612 B 通道。 */
    TB6612_MOTOR_B,
    TB6612_MOTOR_COUNT
} TB6612_Motor_e;

typedef enum {
    /* IN1=IN2=0 且 PWM=高：输出高阻，电机滑行停止。 */
    TB6612_STOP_MODE_COAST = 0,
    /* IN1=IN2=1 且 PWM=高：输出短路制动。 */
    TB6612_STOP_MODE_BRAKE
} TB6612_StopMode_e;

typedef struct {
    /** 两路电机共享的 PWM 频率，单位 Hz。 */
    uint32_t pwm_frequency_hz;
} TB6612Config;

typedef struct {
    /** -100～100，符号代表方向，绝对值代表占空比。 */
    int8_t speed_percent;
    /** 零速度时最近选择的停止方式。 */
    TB6612_StopMode_e stop_mode;
    /** true 表示芯片当前已退出 STBY。 */
    bool standby_released;
} TB6612MotorState;

typedef struct TB6612Instance TB6612Instance;

/** 注册双路驱动，初始化为两路滑行停止且 STBY 低电平。 */
TB6612Instance *TB6612Register(const TB6612Config *config);

/** 设置 -100～100% 速度；正负号控制方向，0 表示滑行停止。 */
bool TB6612SetSpeedPercent(
    TB6612Instance *instance, TB6612_Motor_e motor,
    int8_t speed_percent);

/** 以滑行或短路制动方式停止指定电机。 */
bool TB6612StopMotor(TB6612Instance *instance,
    TB6612_Motor_e motor, TB6612_StopMode_e stop_mode);

/** 释放或进入芯片待机；进入待机会立即关闭两个 H 桥。 */
bool TB6612SetStandby(
    TB6612Instance *instance, bool standby_released);

/** 获取最近一次成功应用的电机状态。 */
bool TB6612GetMotorState(TB6612Instance *instance,
    TB6612_Motor_e motor, TB6612MotorState *state);

/** 无锁进入硬件安全态，供 fault 和紧急停机路径调用。 */
void TB6612EnterSafeState(void);

#endif
