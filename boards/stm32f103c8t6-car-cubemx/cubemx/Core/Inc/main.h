/* USER CODE BEGIN Header */
/* 【合成样例】仿 STM32CubeMX 6.x（STM32CubeF1）生成结构手写，非 CubeMX 真实输出。用户须用 CubeMX 打开 ../f103car.ioc 重新生成。 */
/* USER CODE END Header */
#ifndef __MAIN_H
#define __MAIN_H
#ifdef __cplusplus
extern "C" {
#endif
#include "stm32f1xx_hal.h"
/* USER CODE BEGIN Includes */
/* USER CODE END Includes */
void Error_Handler(void);
#define GPIO_LED_Pin GPIO_PIN_8
#define GPIO_LED_GPIO_Port GPIOA
#define GPIO_BUZZER_Pin GPIO_PIN_1
#define GPIO_BUZZER_GPIO_Port GPIOB
#define KEY1_Pin GPIO_PIN_4
#define KEY1_GPIO_Port GPIOA
#define KEY2_Pin GPIO_PIN_5
#define KEY2_GPIO_Port GPIOA
#define GPIO_MOTOR_B_IN2_Pin GPIO_PIN_10
#define GPIO_MOTOR_B_IN2_GPIO_Port GPIOB
#define GPIO_MOTOR_B_IN1_Pin GPIO_PIN_11
#define GPIO_MOTOR_B_IN1_GPIO_Port GPIOB
#define OLED_SCL_Pin GPIO_PIN_12
#define OLED_SCL_GPIO_Port GPIOB
#define OLED_SDA_Pin GPIO_PIN_13
#define OLED_SDA_GPIO_Port GPIOB
#define GPIO_MOTOR_A_IN1_Pin GPIO_PIN_14
#define GPIO_MOTOR_A_IN1_GPIO_Port GPIOB
#define GPIO_MOTOR_A_IN2_Pin GPIO_PIN_15
#define GPIO_MOTOR_A_IN2_GPIO_Port GPIOB
/* USER CODE BEGIN Private defines */
/* USER CODE END Private defines */
#ifdef __cplusplus
}
#endif
#endif
