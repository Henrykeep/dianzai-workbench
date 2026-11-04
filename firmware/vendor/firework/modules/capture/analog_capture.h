/* 模拟捕获门面：以毫伏、毫赫兹和微秒向业务层公开两路测量。 */
#ifndef ANALOG_CAPTURE_H
#define ANALOG_CAPTURE_H

#include <stdbool.h>
#include <stdint.h>

/** 与两路 ADC 输入一一对应的比较器捕获输入。 */
typedef enum {
    /* PA27 / COMP0 捕获输入。 */
    ANALOG_CAPTURE_INPUT_PA27 = 0,
    /* PA21 / COMP2 捕获输入。 */
    ANALOG_CAPTURE_INPUT_PA21,
    /* 统一输入数量，同时作为枚举范围上限。 */
    ANALOG_CAPTURE_INPUT_COUNT
} AnalogCaptureInput_e;

/** 模拟捕获服务公开的频率测量结果。 */
typedef struct {
    /* 频率，单位为毫赫兹。 */
    uint32_t frequency_millihz;
    /* 周期，单位为微秒。 */
    uint32_t period_microseconds;
    /* BSP 累计捕获的有效边沿数。 */
    uint32_t edge_count;
    /* 每次发布新测量时递增的快照序号。 */
    uint32_t sequence;
} AnalogCaptureMeasurement;

/** 初始化并启动 PA27/COMP0 与 PA21/COMP2 两路捕获。 */
bool AnalogCaptureInit(void);

/** 初始化并启动指定输入的比较器捕获链路。 */
bool AnalogCaptureInitInput(AnalogCaptureInput_e input);

/** 清空两路历史结果并启动捕获。 */
bool AnalogCaptureStart(void);

/** 停止两路捕获。 */
bool AnalogCaptureStop(void);

/** 同时设置两路内部比较阈值，合法范围为 0～3300 mV。 */
bool AnalogCaptureSetThresholdMillivolts(uint16_t threshold_millivolts);

/** 兼容接口：返回 PA27 的比较阈值。 */
uint16_t AnalogCaptureGetThresholdMillivolts(void);

/** 兼容接口：返回 PA27 最近的频率、周期和序号。 */
bool AnalogCaptureReadMeasurement(
    AnalogCaptureMeasurement *measurement);

/** 返回两路捕获是否都正在运行。 */
bool AnalogCaptureIsRunning(void);

/** 启动指定统一输入的捕获链路。 */
bool AnalogCaptureStartInput(AnalogCaptureInput_e input);

/** 停止指定统一输入的捕获链路。 */
bool AnalogCaptureStopInput(AnalogCaptureInput_e input);

/** 设置指定统一输入的比较阈值。 */
bool AnalogCaptureSetInputThresholdMillivolts(
    AnalogCaptureInput_e input, uint16_t threshold_millivolts);

/** 返回指定统一输入的比较阈值。 */
uint16_t AnalogCaptureGetInputThresholdMillivolts(
    AnalogCaptureInput_e input);

/** 读取指定统一输入最近测得的频率和周期。 */
bool AnalogCaptureReadInputMeasurement(AnalogCaptureInput_e input,
    AnalogCaptureMeasurement *measurement);

/** 返回指定统一输入的捕获链路是否正在运行。 */
bool AnalogCaptureIsInputRunning(AnalogCaptureInput_e input);

#endif
