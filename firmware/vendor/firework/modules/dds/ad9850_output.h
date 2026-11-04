/**
 * @file ad9850_output.h
 * @brief 项目默认 AD9850 输出的初始化、控制和状态查询便捷接口。
 */
#ifndef AD9850_OUTPUT_H
#define AD9850_OUTPUT_H

#include <stdbool.h>
#include <stdint.h>

/** AD9850 模块板常用的两个独立输出端。 */
typedef enum {
    AD9850_OUTPUT_WAVEFORM_SINE = 0,
    AD9850_OUTPUT_WAVEFORM_SQUARE,
    AD9850_OUTPUT_WAVEFORM_COUNT
} AD9850OutputWaveform_e;

typedef struct {
    /** 最近一次成功设置的输出频率，单位 Hz。 */
    uint32_t frequency_hz;
    /** 当前选择的硬件输出类型。 */
    AD9850OutputWaveform_e waveform;
    /** true 表示输出已启动。 */
    bool enabled;
} AD9850OutputState;

/** 初始化 AD9850；完成后复位保持有效，模块不会输出信号。 */
bool AD9850OutputInit(uint32_t reference_clock_hz);
/** 更新输出频率；初始化完成后方可调用。 */
bool AD9850OutputSetFrequency(uint32_t frequency_hz);
/** 在 AD9850 支持的正弦和方波输出之间切换。 */
bool AD9850OutputSetWaveform(AD9850OutputWaveform_e waveform);
/** 解除复位并启动当前配置的输出。 */
bool AD9850OutputStart(void);
/** 进入复位状态并关闭输出。 */
bool AD9850OutputStop(void);
/** 复制最近一次成功应用的输出状态。 */
bool AD9850OutputGetState(AD9850OutputState *state);

#endif
