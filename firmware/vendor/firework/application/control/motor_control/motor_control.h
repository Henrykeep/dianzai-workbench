/**
 * @file motor_control.h
 * @brief 双路直流电机目标速度、停止方式和运行状态接口。
 *
 * 调用方只提交目标值，实际 PWM 和方向更新由固定周期任务完成。
 */
#ifndef APPLICATION_CONTROL_MOTOR_CONTROL_H
#define APPLICATION_CONTROL_MOTOR_CONTROL_H

#include <stdbool.h>
#include <stdint.h>

/** TB6612 Application 管理的两路电机。 */
typedef enum {
    TB6612_CONTROL_MOTOR_A = 0,
    TB6612_CONTROL_MOTOR_B,
    TB6612_CONTROL_MOTOR_COUNT
} TB6612Control_Motor_e;

/** 目标速度到达 0 后采用的停止方式。 */
typedef enum {
    TB6612_CONTROL_STOP_COAST = 0,
    TB6612_CONTROL_STOP_BRAKE
} TB6612Control_StopMode_e;

/** 最近一次成功执行的速度和当前目标。 */
typedef struct {
    int8_t current_speed_percent;
    int8_t target_speed_percent;
    TB6612Control_StopMode_e stop_mode;
    bool running;
    bool faulted;
} TB6612ControlStatus;

/** 注册 TB6612 Module 并创建双路共用的平滑调速任务。 */
bool TB6612ControlInit(void);

/**
 * 设置目标速度，范围 -100～100；正负号表示两个方向。
 * 设为 0 时按 app_config.h 中的默认停止方式平滑停机。
 */
bool TB6612ControlSetMotorSpeedPercent(
    TB6612Control_Motor_e motor, int8_t speed_percent);

/** 平滑减速到 0，随后采用指定的滑行或短路制动方式。 */
bool TB6612ControlStopMotor(TB6612Control_Motor_e motor,
    TB6612Control_StopMode_e stop_mode);

/** 立即拉低 STBY 并关闭两个 H 桥，不等待速度斜坡。 */
bool TB6612ControlEmergencyStopAll(void);

/** 获取某一路的目标和最近一次成功应用状态。 */
bool TB6612ControlGetMotorStatus(
    TB6612Control_Motor_e motor, TB6612ControlStatus *status);

/** 返回 Application 和控制任务是否已经完成初始化。 */
bool TB6612ControlIsReady(void);

/** 返回任务历史最小空闲栈，单位为 StackType_t words。 */
uint32_t TB6612ControlGetMinimumFreeStackWords(void);

/** 无锁关闭功率级，供初始化失败、Fault 和框架安全状态使用。 */
void TB6612ControlEnterSafeState(void);

#endif
