/**
 * @file arbitrary_waveform.h
 * @brief 任意波形的 Flash 槽位保存、校验、加载和 DAC 播放接口。
 *
 * Flash 中保存波形，DAC 只使用唯一的运行时播放缓冲区，避免多个播放源抢占 DMA。
 */
#ifndef ARBITRARY_WAVEFORM_H
#define ARBITRARY_WAVEFORM_H

#include <stdbool.h>
#include <stdint.h>

/** Flash 槽位中的任意波形描述；采样数据本身保存在 Flash。 */
typedef struct {
    uint8_t slot_id;
    uint16_t sample_count;
    uint32_t sample_rate_hz;
    uint16_t cycle_count;
    uint32_t actual_frequency_millihz;
    uint16_t minimum_raw;
    uint16_t maximum_raw;
    uint32_t crc32;
    bool valid;
} ArbitraryWaveformInfo;

/** 初始化 Flash 槽位服务并扫描已保存的波形。 */
bool ArbitraryWaveformInit(void);

/** 将一组 12 位 DAC 采样点保存到指定 Flash 槽位。 */
bool ArbitraryWaveformSave(uint8_t slot_id, const uint16_t *samples,
    uint16_t sample_count, uint32_t sample_rate_hz, uint16_t cycle_count);

/** 从 Flash 槽位装载到 DAC 唯一播放缓冲区，但不启动输出。 */
bool ArbitraryWaveformLoad(uint8_t slot_id);

/** 装载指定槽位并启动 DAC 循环播放。 */
bool ArbitraryWaveformStart(uint8_t slot_id);

/** 停止当前任意波形输出。 */
bool ArbitraryWaveformStop(void);

/** 擦除指定槽位。 */
bool ArbitraryWaveformDelete(uint8_t slot_id);

/** 读取槽位元数据；不复制采样数据到 SRAM。 */
bool ArbitraryWaveformGetInfo(uint8_t slot_id,
    ArbitraryWaveformInfo *info);

/** 返回服务是否已经完成初始化。 */
bool ArbitraryWaveformIsInitialized(void);

#endif
