/* 典型“网上下载的驱动”：直接依赖芯片、阻塞延时、全局状态、malloc、double */
#include "stm32f10x_gpio.h"
#include <stdlib.h>
static int g_x;
void OLED_Init(void)
{
    GPIO_SetBits(GPIOB, GPIO_Pin_8);
    GPIOB->ODR |= 1;
    delay_ms(100);
    char *p = malloc(128);
    double k = 1.0 / 3;
    (void)p; (void)k;
    printf("ok");
}
void EXTI0_IRQHandler(void) { g_x++; }
