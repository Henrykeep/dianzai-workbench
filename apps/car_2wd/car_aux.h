/**
 * @file car_aux.h
 * @brief car_2wd 的可选外设（v0.6.0）：板子提供对应资源才启用，不提供就编译成空函数（换板只改 board.yaml）。
 *  - RES_ADC_VBAT：battery 驱动监测电池；先见过 OK、之后进入 CRIT 时请求急停（悬空脚不误触发）（只会“置”急停，从不清除——清除只能由人发 'R'）。
 *  - RES_GPIO_US_TRIG + RES_GPIO_US_ECHO：hcsr04 测前方距离；端口支持 PAL 边沿中断就用中断，否则 100 us 轮询退化为主循环轮询。
 *    前方 < CAR_AUX_STOP_MM 时把前进速度指令钳到 0（后退、转向不受限）。
 * 【仿真】host-sim 上编译运行（无电池 = BAT_NONE，无回波 = 超时，均不干预）；【编译】STM32/MSPM0 未上板。
 */
#ifndef CAR_AUX_H
#define CAR_AUX_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"

#define CAR_AUX_STOP_MM 150.0f

dz_err_t car_aux_init(void);
/** 主循环调用。返回 true = 请求急停（电池过放）。 */
bool car_aux_poll(uint32_t now_ms);
/** 前进速度指令过滤：前方有障碍时返回 0。 */
float car_aux_limit_v(float v_mps);
#endif
