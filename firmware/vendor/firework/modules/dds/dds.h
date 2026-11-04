/**
 * @file dds.h
 * @brief AD9833/AD9850 通用 DDS 设备注册、配置、启停和状态接口。
 */
#ifndef DDS_H
#define DDS_H

#include <stdbool.h>
#include <stdint.h>

/** 当前通用 DDS 层已经实现的芯片后端。 */
typedef enum {
    DDS_CHIP_AD9833 = 0,
    DDS_CHIP_AD9850,
    DDS_CHIP_COUNT
} DDSChip_e;

/** 应用层可使用的逻辑 DDS 设备。 */
typedef enum {
    DDS_DEVICE_OUTPUT_0 = 0,
    DDS_DEVICE_OUTPUT_1,
    DDS_DEVICE_COUNT
} DDS_Device_e;

/** DDS 输出波形。 */
typedef enum {
    DDS_WAVEFORM_SINE = 0,
    DDS_WAVEFORM_TRIANGLE,
    DDS_WAVEFORM_SQUARE,
    DDS_WAVEFORM_COUNT
} DDSWaveform_e;

/** DDS 注册时使用的芯片和初始输出参数。 */
typedef struct {
    DDSChip_e chip;
    uint32_t reference_clock_hz;
    uint32_t initial_frequency_hz;
    uint16_t initial_phase_degrees;
    DDSWaveform_e initial_waveform;
    bool start_enabled;
} DDSConfig;

/** 最近一次成功写入 DDS 的逻辑状态快照。 */
typedef struct {
    DDSChip_e chip;
    uint32_t reference_clock_hz;
    uint32_t frequency_hz;
    uint16_t phase_degrees;
    DDSWaveform_e waveform;
    bool enabled;
} DDSState;

/** DDS 模块不透明实例。 */
typedef struct DDSInstance DDSInstance;

/** 注册 DDS 设备并写入初始频率、相位、波形和启停状态。 */
DDSInstance *DDSRegister(DDS_Device_e device, const DDSConfig *config);

/** 设置输出频率；合法范围为 1 Hz～参考时钟的一半。 */
bool DDSSetFrequency(DDSInstance *instance, uint32_t frequency_hz);

/** 设置输出相位；合法范围为 0～359 度。 */
bool DDSSetPhase(DDSInstance *instance, uint16_t phase_degrees);

/** 设置正弦波、三角波或方波输出；AD9850 仅支持正弦和方波。 */
bool DDSSetWaveform(DDSInstance *instance, DDSWaveform_e waveform);

/** 启动 DDS 输出。 */
bool DDSStart(DDSInstance *instance);

/** 将 DDS 置于复位和休眠状态。 */
bool DDSStop(DDSInstance *instance);

/** 线程安全地读取最近一次成功设置的完整逻辑状态。 */
bool DDSGetState(DDSInstance *instance, DDSState *state);

#endif
