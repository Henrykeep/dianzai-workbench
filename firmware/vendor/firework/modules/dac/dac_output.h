/**
 * @file dac_output.h
 * @brief 项目默认 DAC 波形发生器的配置、播放、停止和诊断接口。
 */
#ifndef DAC_OUTPUT_H
#define DAC_OUTPUT_H

#include <stdbool.h>
#include <stdint.h>

#include "FreeRTOS.h"
#include "task.h"

#define DAC_OUTPUT_MINIMUM_FREQUENCY_HZ (1U)
#define DAC_OUTPUT_SINE_MAXIMUM_FREQUENCY_HZ (62500UL)
#define DAC_OUTPUT_SQUARE_MAXIMUM_FREQUENCY_HZ (500000UL)
#define DAC_OUTPUT_TRIANGLE_MAXIMUM_FREQUENCY_HZ (62500UL)
#define DAC_OUTPUT_SAWTOOTH_MAXIMUM_FREQUENCY_HZ (62500UL)

/** DAC Output Module 支持的输出模式。 */
typedef enum {
    /* DAC 模拟输出关闭。 */
    DAC_OUTPUT_MODE_STOPPED = 0,
    /* 保持最近一次设置的固定直流电压。 */
    DAC_OUTPUT_MODE_DC,
    /* 在最小值和最大值之间输出正弦波。 */
    DAC_OUTPUT_MODE_SINE,
    /* 在最小值和最大值之间输出方波。 */
    DAC_OUTPUT_MODE_SQUARE,
    /* 在最小值和最大值之间输出三角波。 */
    DAC_OUTPUT_MODE_TRIANGLE,
    /* 从最小值向最大值递增后回到最小值。 */
    DAC_OUTPUT_MODE_SAWTOOTH,
    /* 由任意波形服务装载并通过固定更新率流式播放的用户波形。 */
    DAC_OUTPUT_MODE_CUSTOM
} DACOutputMode_e;

/** 周期波形的类型、频率和电压范围。 */
typedef struct {
    DACOutputMode_e mode;
    uint32_t frequency_hz;
    uint16_t minimum_millivolts;
    uint16_t maximum_millivolts;
} DACOutputWaveformConfig;

/** 初始化 PA15 DAC 硬件查找表输出；完成后保持模拟输出关闭。 */
bool DACOutputInit(void);

/** 写入 PA15 DAC 的 12 位原始值，合法范围为 0～4095。 */
bool DACOutputSetRaw(uint16_t raw_value);

/** 设置 PA15 DAC 标称输出电压，合法范围为 0～3300 mV。 */
bool DACOutputSetMillivolts(uint16_t millivolts);

/** 设置 PA15 DAC 满量程百分比，合法范围为 0～100。 */
bool DACOutputSetPercent(uint8_t percent);

/** 按不同波形的频率上限启动 PA15 DAC 周期波形。 */
bool DACOutputConfigureWaveform(
    const DACOutputWaveformConfig *config);

/** 返回指定周期波形的软件频率上限；无效模式返回 0。 */
uint32_t DACOutputGetMaximumFrequencyHz(DACOutputMode_e mode);

/** 启动 PA15 DAC，并恢复最近一次设置值。 */
bool DACOutputStart(void);

/** 关闭 PA15 DAC 模拟输出。 */
bool DACOutputStop(void);

/** 读取最近一次成功设置的 12 位原始值。 */
bool DACOutputGetRaw(uint16_t *raw_value);

/** 读取最近设置值对应的标称毫伏值。 */
bool DACOutputGetMillivolts(uint16_t *millivolts);

/** 返回 PA15 DAC 当前是否已经启用。 */
bool DACOutputIsEnabled(void);

/** 返回 DAC Output Module 是否已经完成初始化。 */
bool DACOutputIsInitialized(void);

/** 返回 DAC Output Module 当前的固定电压或周期波形模式。 */
DACOutputMode_e DACOutputGetMode(void);

/** 读取当前正在输出的周期波形配置；直流或停止时返回 false。 */
bool DACOutputGetWaveformConfig(DACOutputWaveformConfig *config);

/** 返回硬件离散采样率和表长对应的实际输出频率，单位为 mHz。 */
uint32_t DACOutputGetActualFrequencyMillihz(void);

/** 返回上电以来 DAC FIFO 欠载并停止波形的累计次数。 */
uint32_t DACOutputGetFIFOunderrunCount(void);

/** 返回回填任务未在下一轮 DMA 前完成而安全停机的累计次数。 */
uint32_t DACOutputGetStreamRefillMissCount(void);

/** 绑定由 Application Task Manager 创建的高优先级 DAC 回填任务。 */
bool DACOutputSetRefillTaskHandle(TaskHandle_t task_handle);

/** DAC 双缓冲回填任务入口；只能由 Application Task Manager 创建。 */
void DACOutputRefillTask(void *argument);

/**
 * 返回 DAC 模块提供给任意波形调用方的源数据缓冲区。
 * 调用方必须先停止波形，写入完成后再调用
 * DACOutputStartCustomWaveform；DMA 播放期间不得修改该缓冲区。
 */
uint16_t *DACOutputGetCustomWaveformBuffer(void);

/** 返回当前播放缓冲区容量，单位为采样点。 */
uint16_t DACOutputGetCustomWaveformCapacity(void);

/** 使用当前播放缓冲区启动任意波形循环 DMA。 */
bool DACOutputStartCustomWaveform(uint16_t sample_count,
    uint32_t sample_rate_hz, uint16_t cycle_count);

#endif
