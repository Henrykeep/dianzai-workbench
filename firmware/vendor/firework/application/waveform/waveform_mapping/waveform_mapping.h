/**
 * @file waveform_mapping.h
 * @brief 将 PA27 测量结果转换为 DAC、DDS 或 AD9850 输出参数。
 *
 * 映射由测量结果回调异步触发，调用方只需要启动或停止映射服务。
 */
#ifndef WAVEFORM_MAPPING_H
#define WAVEFORM_MAPPING_H

#include <stdbool.h>
#include <stdint.h>

/** PA27 测量结果映射到输出后端时的最近状态。 */
typedef enum {
    WAVEFORM_MAPPING_STATUS_UNINITIALIZED = 0,
    WAVEFORM_MAPPING_STATUS_READY,
    WAVEFORM_MAPPING_STATUS_APPLIED,
    WAVEFORM_MAPPING_STATUS_INVALID_RESULT,
    WAVEFORM_MAPPING_STATUS_UNSUPPORTED_WAVEFORM,
    WAVEFORM_MAPPING_STATUS_FREQUENCY_OUT_OF_RANGE,
    WAVEFORM_MAPPING_STATUS_OUTPUT_ERROR
} WaveformMappingStatus_e;

/** 订阅 PA27 测量结果；每次测量完成后自动更新所选输出后端。 */
bool WaveformMappingInit(void);

/** 返回映射 Application 是否已经完成订阅。 */
bool WaveformMappingIsInitialized(void);

/** 返回最近一次映射状态。 */
WaveformMappingStatus_e WaveformMappingGetStatus(void);

/** 返回最近处理的 PA27 测量结果序号。 */
uint32_t WaveformMappingGetLastSequence(void);

/** 停止编译配置选择的映射输出后端。 */
bool WaveformMappingStop(void);

#endif
