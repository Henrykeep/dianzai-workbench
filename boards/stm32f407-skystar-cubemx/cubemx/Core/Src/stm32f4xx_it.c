/* 【合成样例】仿 CubeMX 生成的中断入口：全部转给 HAL，框架代码不定义任何 IRQHandler。 */
#include "main.h"
#include "stm32f4xx_it.h"
extern DMA_HandleTypeDef hdma_adc1, hdma_usart1_rx, hdma_usart1_tx, hdma_usart2_rx, hdma_usart2_tx;
extern UART_HandleTypeDef huart1, huart2;
extern TIM_HandleTypeDef htim6;
void NMI_Handler(void) { while (1) { } }
void HardFault_Handler(void) { while (1) { } }
void SysTick_Handler(void) { HAL_IncTick(); }
void DMA1_Stream5_IRQHandler(void) { HAL_DMA_IRQHandler(&hdma_usart2_rx); }
void DMA1_Stream6_IRQHandler(void) { HAL_DMA_IRQHandler(&hdma_usart2_tx); }
void DMA2_Stream0_IRQHandler(void) { HAL_DMA_IRQHandler(&hdma_adc1); }
void DMA2_Stream2_IRQHandler(void) { HAL_DMA_IRQHandler(&hdma_usart1_rx); }
void DMA2_Stream7_IRQHandler(void) { HAL_DMA_IRQHandler(&hdma_usart1_tx); }
void USART1_IRQHandler(void) { HAL_UART_IRQHandler(&huart1); }
void USART2_IRQHandler(void) { HAL_UART_IRQHandler(&huart2); }
void TIM6_DAC_IRQHandler(void) { HAL_TIM_IRQHandler(&htim6); }
