/**
 * @file dac.h
 * @brief DAC 逻辑设备的毫伏输出、原始输出和周期波形控制接口。
 */
#ifndef DAC_H
#define DAC_H

#include <stdbool.h>
#include <stdint.h>

/** 应用层可使用的逻辑 DAC 设备。 */
typedef enum {
    /* 通用模拟电压输出，对应 PA15。 */
    DAC_DEVICE_OUTPUT_0 = 0,
    /* 逻辑 DAC 设备总数，同时作为枚举范围上限。 */
    DAC_DEVICE_COUNT
} DAC_Device_e;

/** DAC 注册时使用的初始参数。 */
typedef struct {
    uint16_t initial_raw_value;
    bool start_enabled;
} DACConfig;

/** DAC 模块不透明实例。 */
typedef struct DACInstance DACInstance;

/** 连续波形 DMA 播放期间用于请求生成下一块数据的中断回调。 */
typedef void (*DACWaveformRefillCallback)(
    uint16_t *samples, uint16_t sample_count, void *context);

/** 注册 DAC 设备，并应用初始原始值和启停状态。 */
DACInstance *DACRegister(DAC_Device_e device, const DACConfig *config);

/** 写入 12 位 DAC 原始值，合法范围为 0～4095。 */
bool DACWriteRaw(DACInstance *instance, uint16_t raw_value);

/** 按 3.3 V 标称参考写入毫伏值，合法范围为 0～3300。 */
bool DACWriteMillivolts(DACInstance *instance, uint16_t millivolts);

/** 按满量程百分比写入 DAC，合法范围为 0～100。 */
bool DACWritePercent(DACInstance *instance, uint8_t percent);

/** 使用硬件采样定时器和 DMA 循环输出 12 位查找表。 */
bool DACStartWaveform(DACInstance *instance, const uint16_t *samples,
    uint16_t sample_count, uint32_t sample_rate_hz);

/** 使用双缓冲 DMA 按固定采样率连续输出动态生成的波形。 */
bool DACStartStreamingWaveform(DACInstance *instance,
    uint16_t *buffer_a, uint16_t *buffer_b, uint16_t sample_count,
    uint32_t sample_rate_hz,
    DACWaveformRefillCallback refill_callback, void *context);

/** 提交已经在任务上下文填充完成的空闲流缓冲区。 */
bool DACCommitStreamingBuffer(
    DACInstance *instance, uint16_t *samples);

/** 停止硬件查找表输出，但不关闭 DAC 模拟输出。 */
bool DACStopWaveform(DACInstance *instance);

/** 启动 DAC 模拟输出，并恢复最近一次设置值。 */
bool DACStart(DACInstance *instance);

/** 关闭 DAC 模拟输出。 */
bool DACStop(DACInstance *instance);

/** 读取最近一次成功设置的 12 位原始值。 */
bool DACGetRawValue(DACInstance *instance, uint16_t *raw_value);

/** 将最近设置值按 3.3 V 标称参考换算为毫伏。 */
bool DACGetMillivolts(DACInstance *instance, uint16_t *millivolts);

/** 返回上电以来 DAC FIFO 欠载并停止波形的累计次数。 */
bool DACGetFIFOunderrunCount(
    DACInstance *instance, uint32_t *underrun_count);

/** 读取流缓冲区回填任务超时并安全停机的累计次数。 */
bool DACGetStreamRefillMissCount(
    DACInstance *instance, uint32_t *miss_count);

/** 返回 DAC 硬件当前是否已经启用。 */
bool DACIsEnabled(const DACInstance *instance);

/** 返回 Sample Timer + DMA 波形输出是否仍在运行。 */
bool DACIsWaveformRunning(const DACInstance *instance);

#endif
