/* DDSOutput 为项目默认 AD9833 提供初始化、频率、波形、相位和启停便捷接口。 */
#include "modules/dds/dds_output.h"

#include "application/app_config.h"

#if APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U

#include <stddef.h>

#include "bsp/board_config.h"
#include "modules/dds/dds.h"

#define DDS_OUTPUT_DEFAULT_FREQUENCY_HZ (1000UL)
#define DDS_OUTPUT_DEFAULT_PHASE_DEGREES (0U)

/* 可由 Build Configuration 覆盖；默认采用板级配置中的实际晶振。 */
#ifndef DDS_OUTPUT_REFERENCE_CLOCK_HZ
#define DDS_OUTPUT_REFERENCE_CLOCK_HZ BSP_BOARD_DDS_REFERENCE_CLOCK_HZ
#endif

/* 保存 DDS Output Module 使用的通用 DDS 实例。 */
static DDSInstance *dds_output;

static bool DDSOutputConvertWaveform(DDSOutputWaveform_e output_waveform,
    DDSWaveform_e *waveform);

/* 注册 AD9833 并写入默认参数；初始化完成后保持复位和休眠。 */
bool DDSOutputInit(void)
{
    static const DDSConfig config = {
        DDS_CHIP_AD9833,
        DDS_OUTPUT_REFERENCE_CLOCK_HZ,
        DDS_OUTPUT_DEFAULT_FREQUENCY_HZ,
        DDS_OUTPUT_DEFAULT_PHASE_DEGREES,
        DDS_WAVEFORM_SINE,
        false
    };

    if (dds_output != NULL) {
        return true;
    }

    dds_output = DDSRegister(DDS_DEVICE_OUTPUT_0, &config);
    return dds_output != NULL;
}

/* 检查模块实例后修改 DDS 输出频率。 */
bool DDSOutputSetFrequency(uint32_t frequency_hz)
{
    return (dds_output != NULL) &&
           DDSSetFrequency(dds_output, frequency_hz);
}

/* 检查模块实例后修改 DDS 输出相位。 */
bool DDSOutputSetPhase(uint16_t phase_degrees)
{
    return (dds_output != NULL) &&
           DDSSetPhase(dds_output, phase_degrees);
}

/* 将便捷接口波形枚举映射到通用 DDS 层并写入控制寄存器。 */
bool DDSOutputSetWaveform(DDSOutputWaveform_e output_waveform)
{
    DDSWaveform_e waveform;

    if (!DDSOutputConvertWaveform(output_waveform, &waveform) ||
        (dds_output == NULL)) {
        return false;
    }

    return DDSSetWaveform(dds_output, waveform);
}

/* 检查模块实例后启动 DDS 输出。 */
bool DDSOutputStart(void)
{
    return (dds_output != NULL) && DDSStart(dds_output);
}

/* 检查模块实例后停止 DDS 输出。 */
bool DDSOutputStop(void)
{
    return (dds_output != NULL) && DDSStop(dds_output);
}

/* 取得通用 DDS 状态后转换为便捷接口状态结构。 */
bool DDSOutputGetState(DDSOutputState *state)
{
    DDSState dds_state;

    if ((state == NULL) || (dds_output == NULL) ||
        !DDSGetState(dds_output, &dds_state)) {
        return false;
    }

    switch (dds_state.waveform) {
        case DDS_WAVEFORM_SINE:
            state->waveform = DDS_OUTPUT_WAVEFORM_SINE;
            break;

        case DDS_WAVEFORM_TRIANGLE:
            state->waveform = DDS_OUTPUT_WAVEFORM_TRIANGLE;
            break;

        case DDS_WAVEFORM_SQUARE:
            state->waveform = DDS_OUTPUT_WAVEFORM_SQUARE;
            break;

        default:
            return false;
    }

    state->frequency_hz  = dds_state.frequency_hz;
    state->phase_degrees = dds_state.phase_degrees;
    state->enabled       = dds_state.enabled;
    return true;
}

/* 将便捷接口波形转换为通用 DDS 波形。 */
static bool DDSOutputConvertWaveform(DDSOutputWaveform_e output_waveform,
    DDSWaveform_e *waveform)
{
    if (waveform == NULL) {
        return false;
    }

    switch (output_waveform) {
        case DDS_OUTPUT_WAVEFORM_SINE:
            *waveform = DDS_WAVEFORM_SINE;
            return true;

        case DDS_OUTPUT_WAVEFORM_TRIANGLE:
            *waveform = DDS_WAVEFORM_TRIANGLE;
            return true;

        case DDS_OUTPUT_WAVEFORM_SQUARE:
            *waveform = DDS_WAVEFORM_SQUARE;
            return true;

        default:
            return false;
    }
}

#endif /* APP_ENABLE_WAVEFORM_OUTPUT_DDS */
