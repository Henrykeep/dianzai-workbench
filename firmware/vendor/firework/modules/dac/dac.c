/*
 * DAC Module 在板级 DAC 之上提供毫伏换算、线程安全固定输出和周期波形控制。
 */
#include "modules/dac/dac.h"

#include "application/app_config.h"

#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U

#include <stddef.h>

#include "FreeRTOS.h"
#include "semphr.h"

#include "bsp/dac/bsp_dac.h"

#define DAC_PERCENT_MAXIMUM (100U)

struct DACInstance {
    /* 应用可见的逻辑 DAC 编号。 */
    DAC_Device_e device;
    /* 真实 DAC 外设由 BSP 管理。 */
    BSPDACInstance *dac;
    /* 防止多个任务同时设置同一模拟输出。 */
    SemaphoreHandle_t mutex;
    StaticSemaphore_t mutex_control;
    bool registered;
};

/* DAC 资源数量固定，使用静态实例池。 */
static DACInstance dac_instances[DAC_DEVICE_COUNT];

static bool DACIsValid(const DACInstance *instance);
static bool DACScaleValue(uint32_t value, uint32_t value_maximum,
    uint16_t raw_maximum, uint16_t *raw_value);

/* 注册逻辑 DAC，写入初值并按配置设置启停状态。 */
DACInstance *DACRegister(DAC_Device_e device, const DACConfig *config)
{
    BSP_DAC_Channel_e channel;
    DACInstance *instance;

    if ((device < DAC_DEVICE_OUTPUT_0) || (device >= DAC_DEVICE_COUNT) ||
        (config == NULL)) {
        return NULL;
    }

    switch (device) {
        case DAC_DEVICE_OUTPUT_0:
            channel = BSP_DAC_CHANNEL_OUTPUT_0;
            break;

        default:
            return NULL;
    }

    instance = &dac_instances[device];
    if (instance->registered) {
        return instance;
    }

    instance->mutex = xSemaphoreCreateMutexStatic(&instance->mutex_control);
    if (instance->mutex == NULL) {
        return NULL;
    }

    instance->dac = BSPDACRegister(channel);
    if ((instance->dac == NULL) ||
        !BSPDACWriteRaw(instance->dac, config->initial_raw_value) ||
        !BSPDACSetEnabled(instance->dac, config->start_enabled)) {
        return NULL;
    }

    instance->device     = device;
    instance->registered = true;
    return instance;
}

/* 线程安全地写入指定 12 位 DAC 原始值。 */
bool DACWriteRaw(DACInstance *instance, uint16_t raw_value)
{
    bool result;

    if (!DACIsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = BSPDACWriteRaw(instance->dac, raw_value);
    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 将毫伏值四舍五入换算为 12 位原始值后写入 DAC。 */
bool DACWriteMillivolts(DACInstance *instance, uint16_t millivolts)
{
    uint16_t raw_value;
    uint16_t raw_maximum;
    uint16_t reference_millivolts;
    bool result;

    if (!DACIsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    raw_maximum = BSPDACGetMaximumRawValue(instance->dac);
    reference_millivolts =
        BSPDACGetReferenceMillivolts(instance->dac);
    result = DACScaleValue(millivolts, reference_millivolts,
                 raw_maximum, &raw_value) &&
             BSPDACWriteRaw(instance->dac, raw_value);

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 将 0～100 的满量程百分比换算为 12 位原始值后写入。 */
bool DACWritePercent(DACInstance *instance, uint8_t percent)
{
    uint16_t raw_value;
    uint16_t raw_maximum;
    bool result;

    if (!DACIsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    raw_maximum = BSPDACGetMaximumRawValue(instance->dac);
    result = DACScaleValue(percent, DAC_PERCENT_MAXIMUM,
                 raw_maximum, &raw_value) &&
             BSPDACWriteRaw(instance->dac, raw_value);

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

bool DACStartWaveform(DACInstance *instance, const uint16_t *samples,
    uint16_t sample_count, uint32_t sample_rate_hz)
{
    bool result;

    if (!DACIsValid(instance) || (samples == NULL) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = BSPDACStartWaveform(instance->dac, samples, sample_count,
        (BSP_DAC_Sample_Rate_e)sample_rate_hz);
    (void)xSemaphoreGive(instance->mutex);
    return result;
}

bool DACStartStreamingWaveform(DACInstance *instance,
    uint16_t *buffer_a, uint16_t *buffer_b, uint16_t sample_count,
    uint32_t sample_rate_hz,
    DACWaveformRefillCallback refill_callback, void *context)
{
    bool result;

    if (!DACIsValid(instance) || (buffer_a == NULL) ||
        (buffer_b == NULL) || (refill_callback == NULL) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = BSPDACStartStreamingWaveform(instance->dac,
        buffer_a, buffer_b, sample_count,
        (BSP_DAC_Sample_Rate_e)sample_rate_hz,
        refill_callback, context);
    (void)xSemaphoreGive(instance->mutex);
    return result;
}

bool DACCommitStreamingBuffer(
    DACInstance *instance, uint16_t *samples)
{
    bool result;

    if (!DACIsValid(instance) || (samples == NULL) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = BSPDACCommitStreamingBuffer(instance->dac, samples);
    (void)xSemaphoreGive(instance->mutex);
    return result;
}

bool DACStopWaveform(DACInstance *instance)
{
    bool result;

    if (!DACIsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = BSPDACStopWaveform(instance->dac);
    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 线程安全地启用 DAC，并由 BSP 恢复最近设置值。 */
bool DACStart(DACInstance *instance)
{
    bool result;

    if (!DACIsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = BSPDACSetEnabled(instance->dac, true);
    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 线程安全地关闭 DAC 模拟输出。 */
bool DACStop(DACInstance *instance)
{
    bool result;

    if (!DACIsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = BSPDACSetEnabled(instance->dac, false);
    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 线程安全地读取最近一次成功写入的 12 位设置值。 */
bool DACGetRawValue(DACInstance *instance, uint16_t *raw_value)
{
    if (!DACIsValid(instance) || (raw_value == NULL) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    *raw_value = BSPDACGetRawValue(instance->dac);
    (void)xSemaphoreGive(instance->mutex);
    return true;
}

/* 将最近设置值按标称参考电压四舍五入换算为毫伏。 */
bool DACGetMillivolts(DACInstance *instance, uint16_t *millivolts)
{
    uint16_t raw_value;
    uint16_t raw_maximum;
    uint16_t reference_millivolts;
    uint32_t scaled_value;

    if (!DACIsValid(instance) || (millivolts == NULL) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    raw_value = BSPDACGetRawValue(instance->dac);
    raw_maximum = BSPDACGetMaximumRawValue(instance->dac);
    reference_millivolts =
        BSPDACGetReferenceMillivolts(instance->dac);
    if ((raw_maximum == 0U) || (reference_millivolts == 0U)) {
        (void)xSemaphoreGive(instance->mutex);
        return false;
    }

    scaled_value = ((uint32_t)raw_value * reference_millivolts) +
                   (raw_maximum / 2U);
    *millivolts = (uint16_t)(scaled_value / raw_maximum);

    (void)xSemaphoreGive(instance->mutex);
    return true;
}

bool DACGetFIFOunderrunCount(
    DACInstance *instance, uint32_t *underrun_count)
{
    if (!DACIsValid(instance) || (underrun_count == NULL) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    *underrun_count = BSPDACGetFIFOunderrunCount(instance->dac);
    (void)xSemaphoreGive(instance->mutex);
    return true;
}

bool DACGetStreamRefillMissCount(
    DACInstance *instance, uint32_t *miss_count)
{
    if (!DACIsValid(instance) || (miss_count == NULL) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    *miss_count = BSPDACGetStreamRefillMissCount(instance->dac);
    (void)xSemaphoreGive(instance->mutex);
    return true;
}

/* 返回底层 DAC 硬件当前的实际启用状态。 */
bool DACIsEnabled(const DACInstance *instance)
{
    return DACIsValid(instance) && BSPDACIsEnabled(instance->dac);
}

bool DACIsWaveformRunning(const DACInstance *instance)
{
    return DACIsValid(instance) &&
           BSPDACIsWaveformRunning(instance->dac);
}

/* 将任意满量程值四舍五入缩放到 DAC 原始值范围。 */
static bool DACScaleValue(uint32_t value, uint32_t value_maximum,
    uint16_t raw_maximum, uint16_t *raw_value)
{
    uint32_t scaled_value;

    if ((value_maximum == 0U) || (raw_maximum == 0U) ||
        (value > value_maximum) || (raw_value == NULL)) {
        return false;
    }

    scaled_value = (value * raw_maximum) + (value_maximum / 2U);
    *raw_value = (uint16_t)(scaled_value / value_maximum);
    return true;
}

/* 检查 DAC 模块实例及互斥锁、板级句柄是否有效。 */
static bool DACIsValid(const DACInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->device >= DAC_DEVICE_OUTPUT_0) &&
           (instance->device < DAC_DEVICE_COUNT) &&
           (instance->dac != NULL) && (instance->mutex != NULL);
}

#endif /* APP_ENABLE_WAVEFORM_OUTPUT_DAC */
