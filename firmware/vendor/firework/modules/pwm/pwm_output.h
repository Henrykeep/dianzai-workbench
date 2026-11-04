/**
 * @file pwm_output.h
 * @brief 项目默认 PWM 输出通道的初始化、配置和停止便捷接口。
 */
#ifndef PWM_OUTPUT_H
#define PWM_OUTPUT_H

#include <stdbool.h>
#include <stdint.h>

/** 初始化 PA23 PWM Output Module；完成后保持输出关闭。 */
bool PWMOutputInit(void);

/** 修改 PA23 PWM 输出频率。 */
bool PWMOutputSetFrequency(uint32_t frequency_hz);

/** 修改 PA23 PWM 占空比，合法范围为 0～100。 */
bool PWMOutputSetDutyCycle(uint8_t duty_cycle_percent);

/** 启动 PA23 PWM 输出。 */
bool PWMOutputStart(void);

/** 停止 PA23 PWM 输出。 */
bool PWMOutputStop(void);

#endif
