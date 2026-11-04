/**
 * @file servo_control.h
 * @brief 舵机目标角度、启停请求和运行状态的 Application 接口。
 *
 * 调用方只提交目标状态，实际 PWM 更新由舵机任务按固定周期完成。
 */
#ifndef APPLICATION_CONTROL_SERVO_CONTROL_H
#define APPLICATION_CONTROL_SERVO_CONTROL_H

#include <stdbool.h>
#include <stdint.h>

/** 舵机控制任务管理的逻辑设备。 */
typedef enum {
    /* 第一只舵机：PA23 / TIMG7 CCP0。 */
    SERVO_CONTROL_DEVICE_OUTPUT_0 = 0,
    /* 第二只舵机：PA24 / TIMG7 CCP1。 */
    SERVO_CONTROL_DEVICE_OUTPUT_1,
    SERVO_CONTROL_DEVICE_COUNT
} ServoControl_Device_e;

/** 舵机控制任务对外发布的运行状态。 */
typedef struct {
    uint16_t current_angle_degrees;
    uint16_t target_angle_degrees;
    bool start_requested;
    bool output_enabled;
    bool moving;
    bool faulted;
} ServoControlStatus;

/** 注册 PA23/PA24 舵机并创建任务；初始输出状态由 app_config.h 控制。 */
bool ServoControlInit(void);

/** 设置指定舵机的目标角度；停机状态下只保存目标值。 */
bool ServoControlSetDeviceTargetAngleDegrees(
    ServoControl_Device_e device, uint16_t angle_degrees);

/** 请求启动指定舵机的控制脉冲。 */
bool ServoControlStartDevice(ServoControl_Device_e device);

/** 请求停止指定舵机的控制脉冲。 */
bool ServoControlStopDevice(ServoControl_Device_e device);

/** 读取指定舵机状态；角度为输出命令，不代表真实位置反馈。 */
bool ServoControlGetDeviceStatus(
    ServoControl_Device_e device, ServoControlStatus *status);

/** 兼容接口：设置第一只舵机的目标角度。 */
bool ServoControlSetTargetAngleDegrees(uint16_t angle_degrees);

/** 兼容接口：请求启动第一只舵机。 */
bool ServoControlStart(void);

/** 兼容接口：请求停止第一只舵机。 */
bool ServoControlStop(void);

/** 兼容接口：读取第一只舵机状态。 */
bool ServoControlGetStatus(ServoControlStatus *status);

/** 返回舵机 Application 是否已经完成初始化和任务创建。 */
bool ServoControlIsReady(void);

/** 立即停止全部舵机输出，供初始化失败和安全状态使用。 */
void ServoControlEnterSafeState(void);

#endif
