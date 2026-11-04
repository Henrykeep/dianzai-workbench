/**
 * @file tft_menu.h
 * @brief TFT 显示后端与通用 DisplayMenu 之间的适配接口。
 *
 * 更换 OLED/TFT 时，菜单页面和按键业务不需要跟着复制一份。
 */
#ifndef TFT_MENU_H
#define TFT_MENU_H

#include <stdbool.h>
#include <stdint.h>

/** 初始化 ST7735S TFT，并启动与 OLED 相同的菜单和按键任务。 */
bool TFTMenuInit(void);

/** 与 OLED 兼容；ADC 整帧页不再接受逐点提交。 */
bool TFTMenuSubmitADCWaveformSample(int16_t sample);
/** UART2 收满 1024 点后统一显示最后 128 个原始采样点。 */
bool TFTMenuSubmitUART2WaveformSample(int16_t sample);

#endif
