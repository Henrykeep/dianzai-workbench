/**
 * @file bsp_capture.h
 * @brief 比较器与定时器组合的模拟边沿周期捕获板级接口。
 */
#ifndef BSP_CAPTURE_H
#define BSP_CAPTURE_H

#include <stdbool.h>
#include <stdint.h>

/** COMP 内部 8 位 DAC 使用的标称 VDDA 参考电压。 */
#define BSP_CAPTURE_REFERENCE_MILLIVOLTS (3300U)

/** 板级模拟比较器捕获输入。 */
typedef enum {
    /* PA27：ADC0.0 + COMP0.IN0-，由 TIMG12 捕获。 */
    BSP_CAPTURE_DEVICE_ANALOG_INPUT_0 = 0,
    /* PA21：ADC1.7 + COMP2.IN1-，由 TIMG6 捕获。 */
    BSP_CAPTURE_DEVICE_ANALOG_INPUT_1,
    BSP_CAPTURE_DEVICE_COUNT
} BSP_Capture_Device_e;

/** BSP 捕获结果快照。 */
typedef struct {
    uint32_t period_ticks;
    uint32_t edge_count;
    uint32_t sequence;
} BSPCaptureMeasurement;

/** 捕获设备不透明实例。 */
typedef struct BSPCaptureInstance BSPCaptureInstance;

/** 注册 PA27/COMP0 或 PA21/COMP2 的独立捕获链路。 */
BSPCaptureInstance *BSPCaptureRegister(BSP_Capture_Device_e device);

/** 清空历史结果并启动比较器和捕获定时器。 */
bool BSPCaptureStart(BSPCaptureInstance *instance);

/** 停止比较器事件和捕获定时器。 */
bool BSPCaptureStop(BSPCaptureInstance *instance);

/** 设置对应 COMP 内部 8 位 DAC 阈值，合法范围为 0～3300 mV。 */
bool BSPCaptureSetThresholdMillivolts(
    BSPCaptureInstance *instance, uint16_t threshold_millivolts);

/** 返回当前请求的比较阈值，实例无效时返回 0。 */
uint16_t BSPCaptureGetThresholdMillivolts(
    const BSPCaptureInstance *instance);

/** 读取最近两个有效比较器边沿形成的周期结果。 */
bool BSPCaptureReadMeasurement(BSPCaptureInstance *instance,
    BSPCaptureMeasurement *measurement);

/** 返回捕获链路是否正在运行。 */
bool BSPCaptureIsRunning(const BSPCaptureInstance *instance);

/** 返回捕获定时器的固定计数频率。 */
uint32_t BSPCaptureGetTimerClockHz(
    const BSPCaptureInstance *instance);

#endif
