/* USER CODE BEGIN Header */
/* 【合成样例】仿 STM32CubeMX 6.x 生成结构手写，非 CubeMX 真实输出。用户须用 CubeMX 打开 ../skystar.ioc 重新生成。 */
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
#define GPIO_LED_Pin GPIO_PIN_2
#define GPIO_LED_GPIO_Port GPIOB
#define GPIO_MOTOR_A_IN1_Pin GPIO_PIN_12
#define GPIO_MOTOR_A_IN1_GPIO_Port GPIOB
#define GPIO_MOTOR_A_IN2_Pin GPIO_PIN_13
#define GPIO_MOTOR_A_IN2_GPIO_Port GPIOB
/* USER CODE BEGIN Private defines */
/* USER CODE END Private defines */
#ifdef __cplusplus
}
#endif
#endif
