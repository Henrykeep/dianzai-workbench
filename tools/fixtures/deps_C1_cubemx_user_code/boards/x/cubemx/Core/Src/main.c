#include "main.h"
#include "stm32f4xx_gpio.h"
/* USER CODE BEGIN 2 */
dz_cubemx_start();
pid_step(&g_pid, 1.0f);
/* USER CODE END 2 */
