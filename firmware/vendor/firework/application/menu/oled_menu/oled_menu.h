/**
 * @file oled_menu.h
 * @brief OLED 显示后端与通用 DisplayMenu 之间的适配接口。
 *
 * OLED 页面逻辑不在本文件重复实现，而是转交给 display_menu 模块。
 */
#ifndef OLED_MENU_H
#define OLED_MENU_H

#include <stdbool.h>
#include <stdint.h>

/** 注册两个板载按键、创建菜单控制器并启动菜单任务。 */
bool OLEDMenuInit(void);

/** 兼容旧符号；ADC 整帧页不再接受逐点提交。 */
bool OLEDMenuSubmitADCWaveformSample(int16_t sample);

/** UART2 PB16 页收满 1024 点后统一显示最后 128 个原始采样点。 */
bool OLEDMenuSubmitUART2WaveformSample(int16_t sample);

#endif
