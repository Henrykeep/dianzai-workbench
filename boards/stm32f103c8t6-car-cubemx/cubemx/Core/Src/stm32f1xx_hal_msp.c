/* 【合成样例】仿 CubeMX 生成的 MSP：时钟、引脚、DMA 链接、NVIC。数值与 ../f103car.ioc 一致（F1 无 AF 编号，用默认映射不重映射）。 */
#include "main.h"
extern DMA_HandleTypeDef hdma_usart1_rx, hdma_usart1_tx, hdma_usart2_rx, hdma_usart2_tx;

void HAL_MspInit(void)
{
  __HAL_RCC_AFIO_CLK_ENABLE();
  __HAL_RCC_PWR_CLK_ENABLE();
  HAL_NVIC_SetPriorityGrouping(NVIC_PRIORITYGROUP_4);
  __HAL_AFIO_REMAP_SWJ_NOJTAG();   /* SYS Debug = Serial Wire：释放 PA15/PB3/PB4 */
}

static void pins(GPIO_TypeDef *port, uint32_t p, uint32_t mode, uint32_t pull)
{
  GPIO_InitTypeDef g = {0};
  g.Pin = p; g.Mode = mode; g.Pull = pull; g.Speed = GPIO_SPEED_FREQ_HIGH;
  HAL_GPIO_Init(port, &g);
}

void HAL_TIM_PWM_MspInit(TIM_HandleTypeDef *h)
{
  if (h->Instance == TIM2) {
    __HAL_RCC_TIM2_CLK_ENABLE();
    HAL_NVIC_SetPriority(TIM2_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(TIM2_IRQn);
  }
}

void HAL_TIM_Encoder_MspInit(TIM_HandleTypeDef *h)
{
  if (h->Instance == TIM3) { __HAL_RCC_TIM3_CLK_ENABLE(); __HAL_RCC_GPIOA_CLK_ENABLE(); pins(GPIOA, GPIO_PIN_6|GPIO_PIN_7, GPIO_MODE_INPUT, GPIO_NOPULL); }
  else if (h->Instance == TIM4) { __HAL_RCC_TIM4_CLK_ENABLE(); __HAL_RCC_GPIOB_CLK_ENABLE(); pins(GPIOB, GPIO_PIN_6|GPIO_PIN_7, GPIO_MODE_INPUT, GPIO_NOPULL); }
}

void HAL_TIM_Base_MspInit(TIM_HandleTypeDef *h)
{
  if (h->Instance == TIM1) {
    __HAL_RCC_TIM1_CLK_ENABLE();
    HAL_NVIC_SetPriority(TIM1_UP_IRQn, 1, 0);
    HAL_NVIC_EnableIRQ(TIM1_UP_IRQn);
  }
}

void HAL_TIM_MspPostInit(TIM_HandleTypeDef *h)
{
  if (h->Instance == TIM2) pins(GPIOA, GPIO_PIN_0|GPIO_PIN_1, GPIO_MODE_AF_PP, GPIO_NOPULL);
}

static void dma(DMA_HandleTypeDef *d, DMA_Channel_TypeDef *c, uint32_t dir)
{
  d->Instance = c;
  d->Init.Direction = dir;
  d->Init.PeriphInc = DMA_PINC_DISABLE;
  d->Init.MemInc = DMA_MINC_ENABLE;
  d->Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
  d->Init.MemDataAlignment = DMA_MDATAALIGN_BYTE;
  /* RX 用 Circular（推荐，移植层按 NDTR 读环形缓冲）；TX 用 Normal。用户原工程 RX 是 Normal，移植层也支持 */
  d->Init.Mode = (dir == DMA_PERIPH_TO_MEMORY) ? DMA_CIRCULAR : DMA_NORMAL;
  d->Init.Priority = DMA_PRIORITY_LOW;
  if (HAL_DMA_Init(d) != HAL_OK) Error_Handler();
}

void HAL_UART_MspInit(UART_HandleTypeDef *h)
{
  if (h->Instance == USART1) {
    __HAL_RCC_USART1_CLK_ENABLE(); __HAL_RCC_GPIOA_CLK_ENABLE();
    pins(GPIOA, GPIO_PIN_9, GPIO_MODE_AF_PP, GPIO_NOPULL);
    pins(GPIOA, GPIO_PIN_10, GPIO_MODE_INPUT, GPIO_NOPULL);
    dma(&hdma_usart1_rx, DMA1_Channel5, DMA_PERIPH_TO_MEMORY); __HAL_LINKDMA(h, hdmarx, hdma_usart1_rx);
    dma(&hdma_usart1_tx, DMA1_Channel4, DMA_MEMORY_TO_PERIPH); __HAL_LINKDMA(h, hdmatx, hdma_usart1_tx);
    HAL_NVIC_SetPriority(USART1_IRQn, 0, 0); HAL_NVIC_EnableIRQ(USART1_IRQn);
  } else if (h->Instance == USART2) {
    __HAL_RCC_USART2_CLK_ENABLE(); __HAL_RCC_GPIOA_CLK_ENABLE();
    pins(GPIOA, GPIO_PIN_2, GPIO_MODE_AF_PP, GPIO_NOPULL);
    pins(GPIOA, GPIO_PIN_3, GPIO_MODE_INPUT, GPIO_NOPULL);
    dma(&hdma_usart2_rx, DMA1_Channel6, DMA_PERIPH_TO_MEMORY); __HAL_LINKDMA(h, hdmarx, hdma_usart2_rx);
    dma(&hdma_usart2_tx, DMA1_Channel7, DMA_MEMORY_TO_PERIPH); __HAL_LINKDMA(h, hdmatx, hdma_usart2_tx);
    HAL_NVIC_SetPriority(USART2_IRQn, 0, 0); HAL_NVIC_EnableIRQ(USART2_IRQn);
  }
}
