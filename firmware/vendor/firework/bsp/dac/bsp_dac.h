/**
 * @file bsp_dac.h
 * @brief DAC 固定值、周期 DMA 和双缓冲流式输出的板级接口。
 */
#ifndef BSP_DAC_H
#define BSP_DAC_H

#include <stdbool.h>
#include <stdint.h>

/** LP-MSPM0G3507 板级层向上提供的逻辑 DAC 通道。 */
typedef enum {
    /* DAC0 OUT，固定映射到 PA15。 */
    BSP_DAC_CHANNEL_OUTPUT_0 = 0,
    /* 通道总数，同时作为枚举范围上限。 */
    BSP_DAC_CHANNEL_COUNT
} BSP_DAC_Channel_e;

/** DAC 不透明实例，具体寄存器信息仅保留在 BSP 内部。 */
typedef struct BSPDACInstance BSPDACInstance;

/**
 * 连续波形 DMA 每完成一个缓冲区后，在 DAC 中断中请求回填空闲缓冲区。
 * 回调只能调用 FreeRTOS FromISR 类接口，不能执行阻塞操作。
 */
typedef void (*BSP_DAC_Waveform_Refill_Callback)(
    uint16_t *samples, uint16_t sample_count, void *context);

/** DAC 内部硬件采样定时器支持的离散采样率。 */
typedef enum {
    BSP_DAC_SAMPLE_RATE_500_HZ = 500UL,
    BSP_DAC_SAMPLE_RATE_1_KHZ = 1000UL,
    BSP_DAC_SAMPLE_RATE_2_KHZ = 2000UL,
    BSP_DAC_SAMPLE_RATE_4_KHZ = 4000UL,
    BSP_DAC_SAMPLE_RATE_8_KHZ = 8000UL,
    BSP_DAC_SAMPLE_RATE_16_KHZ = 16000UL,
    BSP_DAC_SAMPLE_RATE_100_KHZ = 100000UL,
    BSP_DAC_SAMPLE_RATE_200_KHZ = 200000UL,
    BSP_DAC_SAMPLE_RATE_500_KHZ = 500000UL,
    BSP_DAC_SAMPLE_RATE_1_MHZ = 1000000UL
} BSP_DAC_Sample_Rate_e;

/** 注册指定板级 DAC 通道；参数非法时返回 NULL。 */
BSPDACInstance *BSPDACRegister(BSP_DAC_Channel_e channel);

/** 写入 12 位 DAC 原始值，合法范围为 0～4095。 */
bool BSPDACWriteRaw(BSPDACInstance *instance, uint16_t raw_value);

/** 使用 DAC Sample Timer + DMA 循环输出 12 位查找表。 */
bool BSPDACStartWaveform(BSPDACInstance *instance,
    const uint16_t *samples, uint16_t sample_count,
    BSP_DAC_Sample_Rate_e sample_rate);

/**
 * 使用两个等长且在内存中连续排列的缓冲区连续输出波形。
 * DMA 以硬件重复模式循环整个双缓冲区，DMA半程中断和DAC完成中断分别
 * 通知上层回填空闲半区；填充完成后必须调用
 * BSPDACCommitStreamingBuffer() 提交。
 */
bool BSPDACStartStreamingWaveform(BSPDACInstance *instance,
    uint16_t *buffer_a, uint16_t *buffer_b, uint16_t sample_count,
    BSP_DAC_Sample_Rate_e sample_rate,
    BSP_DAC_Waveform_Refill_Callback refill_callback, void *context);

/** 提交任务上下文已经填充完成的空闲流缓冲区。 */
bool BSPDACCommitStreamingBuffer(
    BSPDACInstance *instance, uint16_t *samples);

/** 共享 DMA 向量检测到 DAC_CH0 半程事件时调用；仅供 BSP 中断分发使用。 */
void BSPDACHandleDMAEarlyInterrupt(void);

/** 停止 Sample Timer、DMA 和 FIFO，保留 DAC 最近固定值。 */
bool BSPDACStopWaveform(BSPDACInstance *instance);

/** 启用或关闭 DAC 模拟输出。 */
bool BSPDACSetEnabled(BSPDACInstance *instance, bool enabled);

/** 返回 DAC 硬件当前是否已启用。 */
bool BSPDACIsEnabled(const BSPDACInstance *instance);

/** 返回 Sample Timer + DMA 波形输出是否仍在运行。 */
bool BSPDACIsWaveformRunning(const BSPDACInstance *instance);

/** 返回最近一次成功写入的 12 位原始值。 */
uint16_t BSPDACGetRawValue(const BSPDACInstance *instance);

/** 返回 DAC 支持的最大原始值。 */
uint16_t BSPDACGetMaximumRawValue(const BSPDACInstance *instance);

/** 返回用于电压换算的标称参考电压，单位为毫伏。 */
uint16_t BSPDACGetReferenceMillivolts(const BSPDACInstance *instance);

/** 返回上电以来 DAC FIFO 欠载并停止波形的累计次数。 */
uint32_t BSPDACGetFIFOunderrunCount(const BSPDACInstance *instance);

/** 返回流缓冲区未在下一轮 DMA 前填完而安全停机的累计次数。 */
uint32_t BSPDACGetStreamRefillMissCount(
    const BSPDACInstance *instance);

#endif
