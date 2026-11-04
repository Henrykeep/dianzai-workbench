/**
 * @file waveform_output.h
 * @brief 统一封装 DAC、DDS、AD9850 等波形输出后端。
 *
 * 菜单和题目业务只依赖本接口，不直接访问具体芯片驱动或 DMA 缓冲区。
 */
#ifndef WAVEFORM_OUTPUT_H
#define WAVEFORM_OUTPUT_H

#include <stdbool.h>
#include <stdint.h>

/* 各周期波形的软件输出频率边界，单位均为 Hz。 */
#define WAVEFORM_OUTPUT_DAC_MINIMUM_FREQUENCY_HZ (1U)
#define WAVEFORM_OUTPUT_DAC_SINE_MAXIMUM_FREQUENCY_HZ (62500UL)
#define WAVEFORM_OUTPUT_DAC_SQUARE_MAXIMUM_FREQUENCY_HZ (500000UL)
#define WAVEFORM_OUTPUT_DAC_TRIANGLE_MAXIMUM_FREQUENCY_HZ (62500UL)
#define WAVEFORM_OUTPUT_DAC_SAWTOOTH_MAXIMUM_FREQUENCY_HZ (62500UL)
#define WAVEFORM_OUTPUT_AD9850_MINIMUM_FREQUENCY_HZ (1U)

/** 波形输出 Application 当前支持的独立硬件后端。 */
typedef enum {
    WAVEFORM_OUTPUT_BACKEND_DAC = 0,
    WAVEFORM_OUTPUT_BACKEND_DDS,
    WAVEFORM_OUTPUT_BACKEND_AD9850,
    WAVEFORM_OUTPUT_BACKEND_COUNT
} WaveformOutputBackend_e;

/** PA15 DAC 支持的固定电压和周期波形模式。 */
typedef enum {
    WAVEFORM_OUTPUT_DAC_MODE_STOPPED = 0,
    WAVEFORM_OUTPUT_DAC_MODE_DC,
    WAVEFORM_OUTPUT_DAC_MODE_SINE,
    WAVEFORM_OUTPUT_DAC_MODE_SQUARE,
    WAVEFORM_OUTPUT_DAC_MODE_TRIANGLE,
    WAVEFORM_OUTPUT_DAC_MODE_SAWTOOTH,
    WAVEFORM_OUTPUT_DAC_MODE_CUSTOM
} WaveformOutputDACMode_e;

/** PA15 DAC 周期波形的类型、频率和电压范围。 */
typedef struct {
    WaveformOutputDACMode_e mode;
    uint32_t frequency_hz;
    uint16_t minimum_millivolts;
    uint16_t maximum_millivolts;
} WaveformOutputDACConfig;

/** AD9833 DDS 支持的波形类型。 */
typedef enum {
    WAVEFORM_OUTPUT_DDS_WAVEFORM_SINE = 0,
    WAVEFORM_OUTPUT_DDS_WAVEFORM_TRIANGLE,
    WAVEFORM_OUTPUT_DDS_WAVEFORM_SQUARE,
    WAVEFORM_OUTPUT_DDS_WAVEFORM_COUNT
} WaveformOutputDDSWaveform_e;

/** AD9833 DDS 最近一次成功写入的状态。 */
typedef struct {
    uint32_t frequency_hz;
    uint16_t phase_degrees;
    WaveformOutputDDSWaveform_e waveform;
    bool enabled;
} WaveformOutputDDSState;

/** AD9850 模块支持的两个物理输出端：SIN 与 SQ。 */
typedef enum {
    WAVEFORM_OUTPUT_AD9850_WAVEFORM_SINE = 0,
    WAVEFORM_OUTPUT_AD9850_WAVEFORM_SQUARE,
    WAVEFORM_OUTPUT_AD9850_WAVEFORM_COUNT
} WaveformOutputAD9850Waveform_e;

/** AD9850 最近一次成功写入的频率、输出端选择和启停状态。 */
typedef struct {
    uint32_t frequency_hz;
    WaveformOutputAD9850Waveform_e waveform;
    bool enabled;
} WaveformOutputAD9850State;

/** 初始化当前编译配置启用的 DAC、AD9833 DDS 和 AD9850 输出后端。 */
bool WaveformOutputInit(void);

/** 尝试关闭所有已启用输出后端，并汇总各后端的停止结果。 */
bool WaveformOutputStopAll(void);

/** 返回 Waveform Output Application 是否已经完成初始化。 */
bool WaveformOutputIsInitialized(void);

/** 返回指定输出后端是否由当前编译配置启用。 */
bool WaveformOutputBackendIsEnabled(
    WaveformOutputBackend_e backend);

/** 设置 PA15 DAC 的 12 位原始输出值。 */
bool WaveformOutputDACSetRaw(uint16_t raw_value);

/** 设置 PA15 DAC 标称输出电压。 */
bool WaveformOutputDACSetMillivolts(uint16_t millivolts);

/** 按满量程百分比设置 PA15 DAC 输出。 */
bool WaveformOutputDACSetPercent(uint8_t percent);

/** 配置并启动 PA15 DAC 正弦、方波、三角波或锯齿波。 */
bool WaveformOutputDACConfigure(
    const WaveformOutputDACConfig *config);

/** 返回指定 DAC 周期波形的软件频率上限；无效模式返回 0。 */
uint32_t WaveformOutputDACGetMaximumFrequencyHz(
    WaveformOutputDACMode_e mode);

/** 启动 PA15 DAC，并恢复最近一次固定输出值。 */
bool WaveformOutputDACStart(void);

/** 关闭 PA15 DAC 输出。 */
bool WaveformOutputDACStop(void);

/** 读取 PA15 DAC 最近一次成功设置的原始值。 */
bool WaveformOutputDACGetRaw(uint16_t *raw_value);

/** 读取 PA15 DAC 最近设置值对应的标称毫伏值。 */
bool WaveformOutputDACGetMillivolts(uint16_t *millivolts);

/** 返回 PA15 DAC 当前是否已经启用。 */
bool WaveformOutputDACIsEnabled(void);

/** 返回 PA15 DAC 当前的固定电压或周期波形模式。 */
WaveformOutputDACMode_e WaveformOutputDACGetMode(void);

/** 读取当前正在输出的 DAC 周期波形配置。 */
bool WaveformOutputDACGetConfig(WaveformOutputDACConfig *config);

/** 返回 DAC 硬件实际输出频率，单位为 mHz；直流或停止时为 0。 */
uint32_t WaveformOutputDACGetActualFrequencyMillihz(void);

/** 返回上电以来 DAC FIFO 欠载并停止波形的累计次数。 */
uint32_t WaveformOutputDACGetFIFOunderrunCount(void);

/** 返回 DAC 回填任务超时并安全停机的累计次数。 */
uint32_t WaveformOutputDACGetStreamRefillMissCount(void);

/** 设置 AD9833 DDS 输出频率。 */
bool WaveformOutputDDSSetFrequency(uint32_t frequency_hz);

/** 设置 AD9833 DDS 输出相位。 */
bool WaveformOutputDDSSetPhase(uint16_t phase_degrees);

/** 设置 AD9833 DDS 输出波形。 */
bool WaveformOutputDDSSetWaveform(
    WaveformOutputDDSWaveform_e waveform);

/** 启动 AD9833 DDS 当前配置的输出。 */
bool WaveformOutputDDSStart(void);

/** 将 AD9833 DDS 置于复位和休眠状态。 */
bool WaveformOutputDDSStop(void);

/** 读取 AD9833 DDS 最近一次成功设置的状态。 */
bool WaveformOutputDDSGetState(WaveformOutputDDSState *state);

/** 设置 AD9850 频率；范围由 APP_AD9850_MAXIMUM_FREQUENCY_HZ 限制。 */
bool WaveformOutputAD9850SetFrequency(uint32_t frequency_hz);
/** 选择 AD9850 模块板的 SIN 或 SQ 输出端。 */
bool WaveformOutputAD9850SetWaveform(
    WaveformOutputAD9850Waveform_e waveform);
/** 启动 AD9850 当前配置的输出。 */
bool WaveformOutputAD9850Start(void);
/** 将 AD9850 置于复位状态并关闭输出。 */
bool WaveformOutputAD9850Stop(void);
/** 读取 AD9850 最近一次成功设置的状态。 */
bool WaveformOutputAD9850GetState(WaveformOutputAD9850State *state);

#endif
