/* 【合成样例】仿 CubeMX 生成的中断入口：全部转给 HAL，框架代码不定义任何 IRQHandler。 */
#include "main.h"
#include "stm32f1xx_it.h"
extern DMA_HandleTypeDef hdma_usart1_rx, hdma_usart1_tx, hdma_usart2_rx, hdma_usart2_tx;
extern UART_HandleTypeDef huart1, huart2;
extern TIM_HandleTypeDef htim1, htim2;
void NMI_Handler(void) { while (1) { } }
void HardFault_Handler(void) { while (1) { } }
void SysTick_Handler(void) { HAL_IncTick(); }
void DMA1_Channel4_IRQHandler(void) { HAL_DMA_IRQHandler(&hdma_usart1_tx); }
void DMA1_Channel5_IRQHandler(void) { HAL_DMA_IRQHandler(&hdma_usart1_rx); }
void DMA1_Channel6_IRQHandler(void) { HAL_DMA_IRQHandler(&hdma_usart2_rx); }
void DMA1_Channel7_IRQHandler(void) { HAL_DMA_IRQHandler(&hdma_usart2_tx); }
void TIM1_UP_IRQHandler(void) { HAL_TIM_IRQHandler(&htim1); }
void TIM2_IRQHandler(void) { HAL_TIM_IRQHandler(&htim2); }
void USART1_IRQHandler(void) { HAL_UART_IRQHandler(&huart1); }
void USART2_IRQHandler(void) { HAL_UART_IRQHandler(&huart2); }
