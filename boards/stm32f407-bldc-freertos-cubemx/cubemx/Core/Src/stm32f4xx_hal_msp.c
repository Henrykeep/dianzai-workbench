/* 【合成样例】仿 CubeMX 生成的 MSP。数值与 ../bldc_rtos.ioc 一致（中断优先级 5 = configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY）。 */
#include "main.h"

void HAL_MspInit(void)
{
  __HAL_RCC_SYSCFG_CLK_ENABLE();
  __HAL_RCC_PWR_CLK_ENABLE();
  HAL_NVIC_SetPriorityGrouping(NVIC_PRIORITYGROUP_4);
  HAL_NVIC_SetPriority(PendSV_IRQn, 15, 0);
}

static void af(GPIO_TypeDef *port, uint32_t pins, uint32_t alt, uint32_t mode, uint32_t pull)
{
  GPIO_InitTypeDef g = {0};
  g.Pin = pins; g.Mode = mode; g.Pull = pull; g.Speed = GPIO_SPEED_FREQ_VERY_HIGH; g.Alternate = alt;
  HAL_GPIO_Init(port, &g);
}

void HAL_I2C_MspInit(I2C_HandleTypeDef *h)
{
  if (h->Instance == I2C1) {
    __HAL_RCC_GPIOB_CLK_ENABLE();
    af(GPIOB, GPIO_PIN_8|GPIO_PIN_9, GPIO_AF4_I2C1, GPIO_MODE_AF_OD, GPIO_NOPULL);
    __HAL_RCC_I2C1_CLK_ENABLE();
  }
}

void HAL_TIM_PWM_MspInit(TIM_HandleTypeDef *h)
{
  if (h->Instance == TIM2) __HAL_RCC_TIM2_CLK_ENABLE();
}

void HAL_TIM_Encoder_MspInit(TIM_HandleTypeDef *h)
{
  if (h->Instance == TIM3) { __HAL_RCC_TIM3_CLK_ENABLE(); __HAL_RCC_GPIOA_CLK_ENABLE();
    af(GPIOA, GPIO_PIN_6|GPIO_PIN_7, GPIO_AF2_TIM3, GPIO_MODE_AF_PP, GPIO_NOPULL); }
  else if (h->Instance == TIM4) { __HAL_RCC_TIM4_CLK_ENABLE(); __HAL_RCC_GPIOB_CLK_ENABLE();
    af(GPIOB, GPIO_PIN_6|GPIO_PIN_7, GPIO_AF2_TIM4, GPIO_MODE_AF_PP, GPIO_NOPULL); }
}

void HAL_TIM_Base_MspInit(TIM_HandleTypeDef *h)
{
  if (h->Instance == TIM5) {
    __HAL_RCC_TIM5_CLK_ENABLE();
    HAL_NVIC_SetPriority(TIM5_IRQn, 5, 0);
    HAL_NVIC_EnableIRQ(TIM5_IRQn);
  }
}

void HAL_TIM_MspPostInit(TIM_HandleTypeDef *h)
{
  if (h->Instance == TIM2) af(GPIOA, GPIO_PIN_0|GPIO_PIN_1, GPIO_AF1_TIM2, GPIO_MODE_AF_PP, GPIO_NOPULL);
}

void HAL_UART_MspInit(UART_HandleTypeDef *h)
{
  if (h->Instance == UART4) {
    __HAL_RCC_UART4_CLK_ENABLE(); __HAL_RCC_GPIOC_CLK_ENABLE();
    af(GPIOC, GPIO_PIN_10|GPIO_PIN_11, GPIO_AF8_UART4, GPIO_MODE_AF_PP, GPIO_NOPULL);
    HAL_NVIC_SetPriority(UART4_IRQn, 5, 0); HAL_NVIC_EnableIRQ(UART4_IRQn);
  } else if (h->Instance == USART2) {
    __HAL_RCC_USART2_CLK_ENABLE(); __HAL_RCC_GPIOA_CLK_ENABLE();
    af(GPIOA, GPIO_PIN_2|GPIO_PIN_3, GPIO_AF7_USART2, GPIO_MODE_AF_PP, GPIO_NOPULL);
    HAL_NVIC_SetPriority(USART2_IRQn, 5, 0); HAL_NVIC_EnableIRQ(USART2_IRQn);
  }
}
