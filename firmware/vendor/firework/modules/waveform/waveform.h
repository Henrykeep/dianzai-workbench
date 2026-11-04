/**
 * @file waveform.h
 * @brief 128 点环形波形缓存、量程配置和逻辑画布渲染接口。
 */
#ifndef WAVEFORM_H
#define WAVEFORM_H

#include <stdbool.h>
#include <stdint.h>

#include "modules/display/display.h"

/** 波形绘图区和输入量程配置，坐标必须位于 128×64 逻辑画布范围内。 */
typedef struct {
    /** 绘图区左上角 X 坐标。 */
    uint8_t x;
    /** 绘图区左上角 Y 坐标。 */
    uint8_t y;
    /** 绘图区宽度，范围为 2～128 像素。 */
    uint8_t width;
    /** 绘图区高度，范围为 2～64 像素。 */
    uint8_t height;
    /** 映射到绘图区底部的最小采样值。 */
    int16_t minimum;
    /** 映射到绘图区顶部的最大采样值。 */
    int16_t maximum;
    /** 是否绘制中心线和垂直点阵网格。 */
    bool grid_enabled;
} WaveformConfig;

/** Waveform 模块的不透明实例。 */
typedef struct WaveformInstance WaveformInstance;

/**
 * @brief 注册一个绑定到当前显示适配器的滚动波形绘制器。
 *
 * 显示后端必须已经初始化，配置必须满足绘图区不越界且 minimum < maximum。
 * 当前模块使用单个静态实例，失败时返回 NULL。
 */
WaveformInstance *WaveformRegister(
    DisplayInstance *display, const WaveformConfig *config);

/** 清空已经保存的采样值，不会自动清屏或刷新显示设备。 */
bool WaveformReset(WaveformInstance *instance);

/** 修改输入量程，不清除已有采样；minimum 必须小于 maximum。 */
bool WaveformSetRange(
    WaveformInstance *instance, int16_t minimum, int16_t maximum);

/**
 * @brief 从任务上下文提交一个新采样值。
 *
 * 缓冲区最多保存 128 点，写满后覆盖最早的数据。不能从 ISR 调用。
 */
bool WaveformPushSample(WaveformInstance *instance, int16_t sample);

/** 获取最近一次采样值；尚无采样时返回 false。 */
bool WaveformGetLatestSample(
    WaveformInstance *instance, int16_t *sample);

/**
 * @brief 清除绘图区并将当前采样历史绘制到显示帧缓冲区。
 *
 * 本接口不会刷新物理屏幕，成功后仍需调用 DisplayUpdate() 或
 * DisplayUpdatePages()。
 */
bool WaveformRender(WaveformInstance *instance);

#endif
