/**
 * @file dz_cubemx.h
 * @brief CubeMX 工程与本框架的唯一接缝。只需在 CubeMX 生成的 main.c 的 USER CODE 区加三行：
 *
 *   /- USER CODE BEGIN Includes -/   #include "dz_cubemx.h"
 *   /- USER CODE BEGIN 2 -/          dz_cubemx_start();      // 所有 MX_xxx_Init() 之后
 *   /- USER CODE BEGIN 3 -/          dz_cubemx_loop();       // while(1) 循环体内
 *
 * CubeMX 重新生成代码时 USER CODE 区会保留，其余生成代码永远不要手改。
 */
#ifndef DZ_CUBEMX_H
#define DZ_CUBEMX_H

/** 启动 PWM/编码器/串口 DMA 接收，然后调用 app_init()。失败时 LED（若有 RES_GPIO_LED）快闪并停在这里。 */
void dz_cubemx_start(void);
/** 调用一次 app_loop()。裸机放 main.c USER CODE 3（while 内）；FreeRTOS 放 StartDefaultTask 的 for 循环（后面 osDelay(1)）。 */
void dz_cubemx_loop(void);

#include <stdint.h>
/** PAL GPIO 边沿中断分发（PAL 1.2.0）。只在定义了 DZ_CM_NO_EXTI_CALLBACK、自己写 HAL_GPIO_EXTI_Callback 时需要手动调用。 */
void dz_cm_gpio_exti(uint16_t GPIO_Pin);

#ifdef DZ_CM_TIM_TIMEBASE
#include "main.h"
/** 仅 HAL 时基 = TIMx 的工程：在 main.c 的 HAL_TIM_PeriodElapsedCallback 里 USER CODE Callback 1 调用。 */
void dz_cubemx_tim_callback(TIM_HandleTypeDef *htim);
#endif

#endif
