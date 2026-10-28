/* USER CODE BEGIN Header */
/* 【合成样例】仿 STM32CubeMX 6.x（STM32CubeF4）生成结构手写，非 CubeMX 真实输出。用户须用 CubeMX 打开 ../bldc_rtos.ioc 重新生成。 */
/* USER CODE END Header */
#ifndef __MAIN_H
#define __MAIN_H
#ifdef __cplusplus
extern "C" {
#endif
#include "stm32f4xx_hal.h"
/* USER CODE BEGIN Includes */
/* USER CODE END Includes */
void Error_Handler(void);
#define GPIO_MOTOR_A_IN2_Pin GPIO_PIN_12
#define GPIO_MOTOR_A_IN1_Pin GPIO_PIN_13
#define GPIO_MOTOR_B_IN1_Pin GPIO_PIN_14
#define GPIO_MOTOR_B_IN2_Pin GPIO_PIN_15
#define GPIO_MOTOR_GPIO_Port GPIOB
/* USER CODE BEGIN Private defines */
/* USER CODE END Private defines */
#ifdef __cplusplus
}
#endif
#endif
