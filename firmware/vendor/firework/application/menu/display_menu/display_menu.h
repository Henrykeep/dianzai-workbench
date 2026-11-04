/**
 * @file display_menu.h
 * @brief OLED/TFT 共用的菜单、波形、频谱和输出控制页面接口。
 *
 * 显示后端只提供 DisplayInstance；本模块统一处理页面状态、按键和业务调用。
 */
#ifndef DISPLAY_MENU_H
#define DISPLAY_MENU_H

#include <stdbool.h>
#include <stdint.h>

#include "modules/display/display.h"

/**
 * 自定义页可跳转的统一显示路由。
 * 枚举项不随 app_config.h 开关消失，未启用的功能会在请求时返回 false。
 */
typedef enum {
    DISPLAY_MENU_ROUTE_MAIN_MENU = 0,
    DISPLAY_MENU_ROUTE_WAVEFORM_MENU,
    DISPLAY_MENU_ROUTE_WAVEFORM_PA27,
    DISPLAY_MENU_ROUTE_WAVEFORM_PA21,
    DISPLAY_MENU_ROUTE_WAVEFORM_UART2,
    DISPLAY_MENU_ROUTE_WAVEFORM_UART3,
    DISPLAY_MENU_ROUTE_FFT_MENU,
    DISPLAY_MENU_ROUTE_FFT_PA27,
    DISPLAY_MENU_ROUTE_FFT_PA21,
    DISPLAY_MENU_ROUTE_FFT_UART2,
    DISPLAY_MENU_ROUTE_FFT_UART3,
    DISPLAY_MENU_ROUTE_PHASE_PAIR,
    DISPLAY_MENU_ROUTE_MAPPING_MENU,
    DISPLAY_MENU_ROUTE_DAC_OUTPUT_MENU,
    DISPLAY_MENU_ROUTE_ARBITRARY_WAVEFORM_MENU,
    DISPLAY_MENU_ROUTE_PWM_OUTPUT_MENU,
    DISPLAY_MENU_ROUTE_DDS_OUTPUT_MENU,
    DISPLAY_MENU_ROUTE_AD9850_OUTPUT_MENU,
    DISPLAY_MENU_ROUTE_DISPLAY_SETTINGS_MENU,
    DISPLAY_MENU_ROUTE_INFORMATION_MENU,
    DISPLAY_MENU_ROUTE_COUNT
} DisplayMenuRoute_e;

/**
 * 注册按键和通用菜单任务。display 必须由 OLED 或 TFT 后端先完成初始化。
 */
bool DisplayMenuInit(DisplayInstance *display);

/**
 * 从自定义页打开指定菜单或功能页。
 * 返回操作会自动恢复调用前的自定义页状态；仅在
 * CustomPageProcess() 所在的显示任务上下文中调用。
 */
bool DisplayMenuOpenFromCustom(DisplayMenuRoute_e route);

/**
 * 兼容旧接口；ADC 页已改为从 WaveformMeasurement 读取完整快照，
 * 不再接受逐点实时提交。
 */
bool DisplayMenuSubmitADCWaveformSample(int16_t sample);

/** UART2 波形页收集满 1024 点后，统一显示最后 128 个原始采样点。 */
bool DisplayMenuSubmitUART2WaveformSample(int16_t sample);

/** UART3 波形页收集满 128 点后，统一显示完整 128 个原始采样点。 */
bool DisplayMenuSubmitUART3WaveformSample(int16_t sample);

/** 返回显示任务启动以来的最小空闲栈深度（words），尚未采样时为 0。 */
uint32_t DisplayMenuGetMinimumFreeStackWords(void);

#endif
