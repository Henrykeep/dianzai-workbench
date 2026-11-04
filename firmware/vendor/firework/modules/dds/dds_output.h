/**
 * @file dds_output.h
 * @brief 项目默认 AD9833 输出设备的便捷控制和状态查询接口。
 */
#ifndef DDS_OUTPUT_H
#define DDS_OUTPUT_H

#include <stdbool.h>
#include <stdint.h>

/** DDS Output Module 支持的波形类型。 */
typedef enum {
    DDS_OUTPUT_WAVEFORM_SINE = 0,
    DDS_OUTPUT_WAVEFORM_TRIANGLE,
    DDS_OUTPUT_WAVEFORM_SQUARE,
    DDS_OUTPUT_WAVEFORM_COUNT
} DDSOutputWaveform_e;

/** DDS Output Module 最近一次成功设置的状态。 */
typedef struct {
    uint32_t frequency_hz;
    uint16_t phase_degrees;
    DDSOutputWaveform_e waveform;
    bool enabled;
} DDSOutputState;

/** 初始化 AD9833 并写入默认参数；完成后保持复位和休眠。 */
bool DDSOutputInit(void);

/** 设置 AD9833 输出频率，最大为参考时钟的一半。 */
bool DDSOutputSetFrequency(uint32_t frequency_hz);

/** 设置 AD9833 输出相位，合法范围为 0～359 度。 */
bool DDSOutputSetPhase(uint16_t phase_degrees);

/** 设置 AD9833 输出为正弦波、三角波或方波。 */
bool DDSOutputSetWaveform(DDSOutputWaveform_e waveform);

/** 启动 AD9833 当前配置的输出。 */
bool DDSOutputStart(void);

/** 将 AD9833 置于复位和休眠状态。 */
bool DDSOutputStop(void);

/** 读取最近一次成功设置的 DDS Output Module 状态。 */
bool DDSOutputGetState(DDSOutputState *state);

#endif
