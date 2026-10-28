/* 【合成样例】仿 CubeMX 生成的 MSP：时钟、引脚复用、DMA 链接、NVIC。数值与 ../skystar.ioc 一致。 */
#include "main.h"
extern DMA_HandleTypeDef hdma_usart1_rx, hdma_usart1_tx, hdma_usart2_rx, hdma_usart2_tx;

void HAL_MspInit(void)
{
  __HAL_RCC_SYSCFG_CLK_ENABLE();
  __HAL_RCC_PWR_CLK_ENABLE();
  HAL_NVIC_SetPriorityGrouping(NVIC_PRIORITYGROUP_4);
}

static void af(GPIO_TypeDef *port, uint32_t pins, uint32_t alt, uint32_t pull)
{
  GPIO_InitTypeDef g = {0};
  g.Pin = pins; g.Mode = GPIO_MODE_AF_PP; g.Pull = pull; g.Speed = GPIO_SPEED_FREQ_VERY_HIGH; g.Alternate = alt;
  HAL_GPIO_Init(port, &g);
}

void HAL_ADC_MspInit(ADC_HandleTypeDef *h)
{
  if (h->Instance == ADC1) {
    GPIO_InitTypeDef g = {0};
    __HAL_RCC_ADC1_CLK_ENABLE();
    g.Pin = GPIO_PIN_0; g.Mode = GPIO_MODE_ANALOG; g.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(GPIOC, &g);
  }
}

void HAL_TIM_PWM_MspInit(TIM_HandleTypeDef *h)
{
  if (h->Instance == TIM1) __HAL_RCC_TIM1_CLK_ENABLE();
  else if (h->Instance == TIM3) __HAL_RCC_TIM3_CLK_ENABLE();
}

void HAL_TIM_Encoder_MspInit(TIM_HandleTypeDef *h)
{
  if (h->Instance == TIM4) { __HAL_RCC_TIM4_CLK_ENABLE(); af(GPIOD, GPIO_PIN_12|GPIO_PIN_13, GPIO_AF2_TIM4, GPIO_PULLUP); }
}

void HAL_TIM_Base_MspInit(TIM_HandleTypeDef *h)
{
  if (h->Instance == TIM6) {
    __HAL_RCC_TIM6_CLK_ENABLE();
    HAL_NVIC_SetPriority(TIM6_DAC_IRQn, 1, 0);
    HAL_NVIC_EnableIRQ(TIM6_DAC_IRQn);
  }
}

void HAL_TIM_MspPostInit(TIM_HandleTypeDef *h)
{
  if (h->Instance == TIM1) af(GPIOA, GPIO_PIN_8, GPIO_AF1_TIM1, GPIO_NOPULL);
  else if (h->Instance == TIM3) af(GPIOC, GPIO_PIN_6|GPIO_PIN_7, GPIO_AF2_TIM3, GPIO_NOPULL);
}

static void dma(DMA_HandleTypeDef *d, DMA_Stream_TypeDef *s, uint32_t ch, uint32_t dir, uint32_t mode)
{
  d->Instance = s;
  d->Init.Channel = ch;
  d->Init.Direction = dir;
  d->Init.PeriphInc = DMA_PINC_DISABLE;
  d->Init.MemInc = DMA_MINC_ENABLE;
  d->Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
  d->Init.MemDataAlignment = DMA_MDATAALIGN_BYTE;
  d->Init.Mode = mode;
  d->Init.Priority = DMA_PRIORITY_LOW;
  d->Init.FIFOMode = DMA_FIFOMODE_DISABLE;
  if (HAL_DMA_Init(d) != HAL_OK) Error_Handler();
}

void HAL_UART_MspInit(UART_HandleTypeDef *h)
{
  if (h->Instance == USART1) {
    __HAL_RCC_USART1_CLK_ENABLE();
    af(GPIOA, GPIO_PIN_9|GPIO_PIN_10, GPIO_AF7_USART1, GPIO_PULLUP);
    dma(&hdma_usart1_rx, DMA2_Stream2, DMA_CHANNEL_4, DMA_PERIPH_TO_MEMORY, DMA_CIRCULAR);
    __HAL_LINKDMA(h, hdmarx, hdma_usart1_rx);
    dma(&hdma_usart1_tx, DMA2_Stream7, DMA_CHANNEL_4, DMA_MEMORY_TO_PERIPH, DMA_NORMAL);
    __HAL_LINKDMA(h, hdmatx, hdma_usart1_tx);
    HAL_NVIC_SetPriority(USART1_IRQn, 5, 0); HAL_NVIC_EnableIRQ(USART1_IRQn);
  } else if (h->Instance == USART2) {
    __HAL_RCC_USART2_CLK_ENABLE();
    af(GPIOA, GPIO_PIN_2|GPIO_PIN_3, GPIO_AF7_USART2, GPIO_PULLUP);
    dma(&hdma_usart2_rx, DMA1_Stream5, DMA_CHANNEL_4, DMA_PERIPH_TO_MEMORY, DMA_CIRCULAR);
    __HAL_LINKDMA(h, hdmarx, hdma_usart2_rx);
    dma(&hdma_usart2_tx, DMA1_Stream6, DMA_CHANNEL_4, DMA_MEMORY_TO_PERIPH, DMA_NORMAL);
    __HAL_LINKDMA(h, hdmatx, hdma_usart2_tx);
    HAL_NVIC_SetPriority(USART2_IRQn, 5, 0); HAL_NVIC_EnableIRQ(USART2_IRQn);
  }
}
