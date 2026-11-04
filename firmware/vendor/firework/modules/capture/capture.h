/* Capture 硬件无关接口：管理比较阈值并读取定时器捕获结果。 */
#ifndef CAPTURE_H
#define CAPTURE_H

#include <stdbool.h>
#include <stdint.h>

/** 应用可使用的逻辑捕获设备。 */
typedef enum {
    /* PA27 / COMP0 模拟比较器输入。 */
    CAPTURE_DEVICE_ANALOG_INPUT_0 = 0,
    /* PA21 / COMP2 模拟比较器输入。 */
    CAPTURE_DEVICE_ANALOG_INPUT_1,
    /* 逻辑捕获设备数量，同时作为枚举范围上限。 */
    CAPTURE_DEVICE_COUNT
} Capture_Device_e;

/** 捕获实例的初始配置。 */
typedef struct {
    /* 比较器阈值，单位为毫伏。 */
    uint16_t threshold_millivolts;
    /* true 表示注册成功后立即启动捕获。 */
    bool start_enabled;
} CaptureConfig;

/** 与硬件无关的周期和频率测量结果。 */
typedef struct {
    /* 相邻有效边沿之间的定时器计数。 */
    uint32_t period_ticks;
    /* 由定时器时钟换算的频率，单位为毫赫兹。 */
    uint32_t frequency_millihz;
    /* BSP 累计捕获的有效边沿数。 */
    uint32_t edge_count;
    /* 每次发布新测量时递增的快照序号。 */
    uint32_t sequence;
} CaptureMeasurement;

/** Capture 模块不透明实例。 */
typedef struct CaptureInstance CaptureInstance;

/** 注册捕获设备、设置阈值，并按配置决定是否立即启动。 */
CaptureInstance *CaptureRegister(
    Capture_Device_e device, const CaptureConfig *config);

/** 启动捕获。 */
bool CaptureStart(CaptureInstance *instance);

/** 停止捕获。 */
bool CaptureStop(CaptureInstance *instance);

/** 设置模拟比较阈值，合法范围由 BSP 决定。 */
bool CaptureSetThresholdMillivolts(
    CaptureInstance *instance, uint16_t threshold_millivolts);

/** 返回当前比较阈值。 */
uint16_t CaptureGetThresholdMillivolts(
    const CaptureInstance *instance);

/** 读取最近周期并换算成毫赫兹。 */
bool CaptureReadMeasurement(
    CaptureInstance *instance, CaptureMeasurement *measurement);

/** 返回捕获链路是否运行。 */
bool CaptureIsRunning(const CaptureInstance *instance);

/** 返回底层捕获定时器时钟，单位为 Hz。 */
uint32_t CaptureGetTimerClockHz(const CaptureInstance *instance);

#endif
