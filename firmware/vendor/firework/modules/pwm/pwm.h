/**
 * @file pwm.h
 * @brief 逻辑 PWM 通道的频率、占空比、脉宽、启停和状态接口。
 */
#ifndef PWM_H
#define PWM_H

#include <stdbool.h>
#include <stdint.h>

/** 应用层可使用的逻辑 PWM 设备。 */
typedef enum {
    /* 通用 PWM 输出，对应 PA23。 */
    PWM_DEVICE_OUTPUT_0 = 0,
    /* 第二路 PWM 输出，对应 PA24。 */
    PWM_DEVICE_OUTPUT_1,
    /* 逻辑 PWM 设备总数，同时作为枚举范围上限。 */
    PWM_DEVICE_COUNT
} PWM_Device_e;

/** PWM 注册时使用的初始参数。 */
typedef struct {
    uint32_t frequency_hz;
    uint8_t duty_cycle_percent;
    bool start_enabled;
} PWMConfig;

/** PWM 模块不透明实例。 */
typedef struct PWMInstance PWMInstance;

/** 注册 PWM 设备并应用初始频率、占空比和启停状态。 */
PWMInstance *PWMRegister(PWM_Device_e device, const PWMConfig *config);

/** 修改 PWM 频率；超出硬件计数范围时返回 false。 */
bool PWMSetFrequency(PWMInstance *instance, uint32_t frequency_hz);

/** 修改 PWM 占空比，合法范围为 0～100。 */
bool PWMSetDutyCycle(PWMInstance *instance, uint8_t duty_cycle_percent);

/** 按当前频率设置高电平脉宽，单位为微秒；脉宽不得超过一个 PWM 周期。 */
bool PWMSetPulseWidthMicroseconds(
    PWMInstance *instance, uint32_t pulse_width_microseconds);

/** 启动 PWM 输出。 */
bool PWMStart(PWMInstance *instance);

/** 停止 PWM 输出。 */
bool PWMStop(PWMInstance *instance);

#endif
