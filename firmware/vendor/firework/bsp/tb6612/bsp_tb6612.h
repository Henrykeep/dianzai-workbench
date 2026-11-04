/**
 * @file bsp_tb6612.h
 * @brief TB6612 双路电机 PWM、方向、待机和安全关断板级接口。
 */
#ifndef BSP_TB6612_H
#define BSP_TB6612_H

#include <stdbool.h>
#include <stdint.h>

/** TB6612 板级双路电机通道。 */
typedef enum {
    BSP_TB6612_MOTOR_A = 0,
    BSP_TB6612_MOTOR_B,
    BSP_TB6612_MOTOR_COUNT
} BSP_TB6612_Motor_e;

typedef struct BSPTB6612Instance BSPTB6612Instance;

/** 注册 TB6612 板级资源并立即保持 STBY 低电平。 */
BSPTB6612Instance *BSPTB6612Register(void);

/** 配置 PWMA/PWMB 共用频率；仅允许在 STBY 状态下修改。 */
bool BSPTB6612ConfigurePWM(
    BSPTB6612Instance *instance, uint32_t frequency_hz);

/** 设置单路方向输入和 0～100% PWM 占空比。 */
bool BSPTB6612SetMotorOutput(BSPTB6612Instance *instance,
    BSP_TB6612_Motor_e motor, bool input_1_high,
    bool input_2_high, uint8_t duty_cycle_percent);

/** true 释放 STBY 并启动 PWM；false 先拉低 STBY 再关闭 PWM。 */
bool BSPTB6612SetStandby(
    BSPTB6612Instance *instance, bool standby_released);

/** 无锁关闭 STBY、PWM 和方向输出，供 fault 路径调用。 */
void BSPTB6612EnterSafeState(void);

#endif
