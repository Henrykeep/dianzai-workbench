/* 【合成样例】仿 CubeMX 生成的中断入口。FreeRTOS 工程：SVC_Handler/PendSV_Handler 由 FreeRTOSConfig.h 映射到内核，
 * SysTick_Handler 在 cmsis_os2.c；HAL 时基 TIM1 的中断在这里转给 HAL。 */
#include "main.h"
#include "stm32f4xx_it.h"
extern TIM_HandleTypeDef htim1, htim5;
extern UART_HandleTypeDef huart4, huart2;
void NMI_Handler(void) { while (1) { } }
void HardFault_Handler(void) { while (1) { } }
void TIM1_UP_TIM10_IRQHandler(void) { HAL_TIM_IRQHandler(&htim1); }
void TIM5_IRQHandler(void) { HAL_TIM_IRQHandler(&htim5); }
void UART4_IRQHandler(void) { HAL_UART_IRQHandler(&huart4); }
void USART2_IRQHandler(void) { HAL_UART_IRQHandler(&huart2); }
