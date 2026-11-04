/**
 * @file servo.h
 * @brief 双路舵机角度、脉宽、启停和状态查询接口。
 */
#ifndef SERVO_H
#define SERVO_H

#include <stdbool.h>
#include <stdint.h>

/** 应用层可使用的逻辑舵机设备。 */
typedef enum {
    /* 使用 PA23 / TIMG7 CCP0 的舵机输出。 */
    SERVO_DEVICE_OUTPUT_0 = 0,
    /* 使用 PA24 / TIMG7 CCP1 的第二路舵机输出。 */
    SERVO_DEVICE_OUTPUT_1,
    /* 逻辑舵机设备总数，同时作为枚举范围上限。 */
    SERVO_DEVICE_COUNT
} Servo_Device_e;

/** 舵机注册配置；角度会线性映射到最小和最大高电平脉宽。 */
typedef struct {
    uint16_t minimum_pulse_width_microseconds;
    uint16_t maximum_pulse_width_microseconds;
    uint16_t maximum_angle_degrees;
    uint16_t initial_angle_degrees;
    bool start_enabled;
} ServoConfig;

/** 舵机模块不透明实例。 */
typedef struct ServoInstance ServoInstance;

/** 注册舵机、设置 50 Hz 控制周期，并应用初始角度和启停状态。 */
ServoInstance *ServoRegister(
    Servo_Device_e device, const ServoConfig *config);

/** 设置目标角度，合法范围为 0～配置的 maximum_angle_degrees。 */
bool ServoSetAngleDegrees(
    ServoInstance *instance, uint16_t angle_degrees);

/** 直接设置高电平脉宽，合法范围由注册配置决定。 */
bool ServoSetPulseWidthMicroseconds(
    ServoInstance *instance, uint16_t pulse_width_microseconds);

/** 启动 50 Hz 舵机控制脉冲。 */
bool ServoStart(ServoInstance *instance);

/** 停止控制脉冲并关闭对应引脚的 PWM 输出方向。 */
bool ServoStop(ServoInstance *instance);

/** 读取最近一次成功设置的目标角度。 */
bool ServoGetAngleDegrees(
    ServoInstance *instance, uint16_t *angle_degrees);

/** 读取最近一次成功设置的高电平脉宽。 */
bool ServoGetPulseWidthMicroseconds(
    ServoInstance *instance, uint16_t *pulse_width_microseconds);

/** 返回舵机控制脉冲当前是否已启动。 */
bool ServoIsEnabled(const ServoInstance *instance);

#endif
