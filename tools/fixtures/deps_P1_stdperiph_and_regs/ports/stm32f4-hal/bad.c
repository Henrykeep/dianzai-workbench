#include "stm32f4xx_gpio.h"
void f(void){ GPIO_Init(0,0); RCC_AHB1PeriphClockCmd(1,1); TIM2->CNT = 0; htim2.Instance->CCR1 = 5; }
/* DZ-REG-OK: */
void g(void){ TIM5->CNT = 0; }
/* DZ-REG-OK: HAL 没有在 ISR 内 O(1) 读 32 位计数的接口 */
unsigned h(void){ return TIM5->CNT; }
