/* 将应用层逻辑 ADC 设备封装为线程安全的 BSP 采集接口。 */
#include "modules/adc/adc.h"

#include "application/app_config.h"

#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U)

#include <stddef.h>

#include "FreeRTOS.h"
#include "semphr.h"

#include "bsp/adc/bsp_adc.h"

/* 每个逻辑设备保存固定的 BSP 映射及阈值采集回调上下文。 */
struct ADCInstance {
    ADC_Device_e device;
    BSPADCInstance *adc;
    bool registered;
    ADCThresholdCaptureCallback_t threshold_callback;
    void *threshold_context;
};

/* 编译期校验模块回调与 BSP 回调的二进制签名保持一致。 */
typedef char ADCDirectCaptureCallbackSignatureMustMatchBSP[
    (sizeof(ADCDirectCaptureCallback_t) ==
        sizeof(BSPADCDirectCaptureCallback_t)) ? 1 : -1];
typedef char ADCSynchronizedCaptureCallbackSignatureMustMatchBSP[
    (sizeof(ADCSynchronizedCaptureCallback_t) ==
        sizeof(BSPADCSynchronizedCaptureCallback_t)) ? 1 : -1];
typedef char ADCThresholdCaptureCallbackSignatureMustMatchBSP[
    (sizeof(ADCThresholdCaptureCallback_t) ==
        sizeof(BSPADCThresholdCaptureCallback_t)) ? 1 : -1];

/* 实例和互斥锁均为静态资源；互斥锁串行化采集状态切换及参数读取。 */
static ADCInstance adc_instances[ADC_DEVICE_COUNT];
static SemaphoreHandle_t adc_mutex;
static StaticSemaphore_t adc_mutex_control;

static bool ADCIsValid(const ADCInstance *instance);
static void ADCHandleThresholdCaptureEvent(
    BSPADCThresholdEvent_e event, uint32_t sequence, void *context);
static bool ADCConvertRawToMillivoltsLocked(
    ADCInstance *instance, uint16_t raw_value, uint16_t *millivolts);

/* 注册采用幂等单例语义，同一逻辑设备重复注册返回原实例。 */
ADCInstance *ADCRegister(ADC_Device_e device)
{
    BSP_ADC_Channel_e channel;
    ADCInstance *instance;

    if ((device < ADC_DEVICE_INPUT_0) || (device >= ADC_DEVICE_COUNT)) {
        return NULL;
    }
    channel = (device == ADC_DEVICE_INPUT_1)
                  ? BSP_ADC_CHANNEL_INPUT_1
                  : BSP_ADC_CHANNEL_INPUT_0;
    instance = &adc_instances[device];
    if (instance->registered) {
        return instance;
    }
    if (adc_mutex == NULL) {
        adc_mutex = xSemaphoreCreateMutexStatic(&adc_mutex_control);
        if (adc_mutex == NULL) {
            return NULL;
        }
    }
    instance->adc = BSPADCRegister(channel);
    if (instance->adc == NULL) {
        return NULL;
    }
    instance->device = device;
    instance->registered = true;
    return instance;
}

bool ADCStartDirectCapture(ADCInstance *instance,
    uint16_t *buffer, size_t buffer_capacity, size_t sample_count,
    uint32_t sample_rate_hz,
    ADCDirectCaptureCallback_t callback, void *context)
{
    bool result;

    if (!ADCIsValid(instance) || (buffer == NULL) ||
        (buffer_capacity < sample_count) || (sample_count == 0U) ||
        (sample_rate_hz == 0UL) ||
        (callback == NULL) ||
        (xSemaphoreTake(adc_mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }
    result = BSPADCStartDirectCapture(instance->adc,
        buffer, buffer_capacity, sample_count, sample_rate_hz,
        callback, context);
    (void)xSemaphoreGive(adc_mutex);
    return result;
}

/* 阈值链路需跨越 ADC/DMA 中断保存回调，启动失败时立即撤销该上下文。 */
bool ADCStartThresholdTriggeredCapture(
    ADCInstance *instance, uint16_t *buffer, size_t buffer_capacity,
    size_t sample_count, uint32_t sample_rate_hz,
    uint16_t high_threshold_raw, uint16_t low_threshold_raw,
    ADCThresholdCaptureCallback_t callback, void *context)
{
    bool result;

    if (!ADCIsValid(instance) || (buffer == NULL) ||
        (buffer_capacity < sample_count) || (sample_count < 2U) ||
        (sample_count > UINT16_MAX) || (sample_rate_hz == 0UL) ||
        (callback == NULL) ||
        (xSemaphoreTake(adc_mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }
    instance->threshold_callback = callback;
    instance->threshold_context = context;
    result = BSPADCStartThresholdTriggeredCapture(instance->adc,
        buffer, buffer_capacity, sample_count, sample_rate_hz,
        high_threshold_raw, low_threshold_raw,
        ADCHandleThresholdCaptureEvent, instance);
    if (!result) {
        instance->threshold_callback = NULL;
        instance->threshold_context = NULL;
    }
    (void)xSemaphoreGive(adc_mutex);
    return result;
}

bool ADCStartSynchronizedCapture(
    ADCInstance *first_instance, uint16_t *first_buffer,
    size_t first_buffer_capacity, ADCInstance *second_instance,
    uint16_t *second_buffer, size_t second_buffer_capacity,
    size_t sample_count, uint32_t sample_rate_hz,
    ADCSynchronizedCaptureCallback_t callback, void *context)
{
    bool result;

    if (!ADCIsValid(first_instance) || !ADCIsValid(second_instance) ||
        (first_instance == second_instance) ||
        (first_buffer == NULL) || (second_buffer == NULL) ||
        (first_buffer_capacity < sample_count) ||
        (second_buffer_capacity < sample_count) ||
        (sample_count == 0U) || (callback == NULL) ||
        (xSemaphoreTake(adc_mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }
    result = BSPADCStartSynchronizedCapture(
        first_instance->adc, first_buffer, first_buffer_capacity,
        second_instance->adc, second_buffer, second_buffer_capacity,
        sample_count, sample_rate_hz, callback, context);
    (void)xSemaphoreGive(adc_mutex);
    return result;
}

bool ADCFinishSynchronizedCapture(void)
{
    bool result;

    if ((adc_mutex == NULL) ||
        (xSemaphoreTake(adc_mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }
    result = BSPADCFinishSynchronizedCapture();
    (void)xSemaphoreGive(adc_mutex);
    return result;
}

bool ADCIsSynchronizedCaptureActive(void)
{
    return BSPADCIsSynchronizedCaptureActive();
}

bool ADCFinishDirectCapture(ADCInstance *instance)
{
    bool result;

    if (!ADCIsValid(instance) ||
        (xSemaphoreTake(adc_mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }
    result = BSPADCFinishDirectCapture(instance->adc);
    (void)xSemaphoreGive(adc_mutex);
    return result;
}

bool ADCFinishThresholdTriggeredCapture(ADCInstance *instance)
{
    bool result;

    if (!ADCIsValid(instance) ||
        (xSemaphoreTake(adc_mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }
    result = BSPADCFinishThresholdTriggeredCapture(instance->adc);
    if (result) {
        instance->threshold_callback = NULL;
        instance->threshold_context = NULL;
    }
    (void)xSemaphoreGive(adc_mutex);
    return result;
}

bool ADCIsDirectCaptureActive(const ADCInstance *instance)
{
    return ADCIsValid(instance) &&
           BSPADCIsDirectCaptureActive(instance->adc);
}

bool ADCIsThresholdTriggeredCaptureActive(const ADCInstance *instance)
{
    return ADCIsValid(instance) &&
           BSPADCIsThresholdTriggeredCaptureActive(instance->adc);
}

static void ADCHandleThresholdCaptureEvent(
    BSPADCThresholdEvent_e event, uint32_t sequence, void *context)
{
    ADCInstance *instance = (ADCInstance *)context;
    ADCThresholdCaptureCallback_t callback;
    ADCThresholdEvent_e adc_event;

    /* 此桥接函数运行在 ADC/DMA 中断上下文，只做事件映射和回调转发。 */
    if ((instance == NULL) || !instance->registered) {
        return;
    }
    callback = instance->threshold_callback;
    adc_event = (event == BSP_ADC_THRESHOLD_SIGNAL_REARMED)
        ? ADC_THRESHOLD_SIGNAL_REARMED
        : ADC_THRESHOLD_CAPTURE_COMPLETE;
    if (callback != NULL) {
        callback(adc_event, sequence, instance->threshold_context);
    }
}

uint32_t ADCGetDefaultSampleRateHz(const ADCInstance *instance)
{
    return ADCIsValid(instance)
               ? BSPADCGetDefaultSampleRateHz(instance->adc)
               : 0UL;
}

bool ADCIsSampleRateSupported(uint32_t sample_rate_hz)
{
    return BSPADCIsSampleRateSupported(sample_rate_hz);
}

bool ADCConvertRawToMillivolts(
    ADCInstance *instance, uint16_t raw_value, uint16_t *millivolts)
{
    bool result;

    if (!ADCIsValid(instance) || (millivolts == NULL) ||
        (xSemaphoreTake(adc_mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }
    result = ADCConvertRawToMillivoltsLocked(
        instance, raw_value, millivolts);
    (void)xSemaphoreGive(adc_mutex);
    return result;
}

static bool ADCConvertRawToMillivoltsLocked(
    ADCInstance *instance, uint16_t raw_value, uint16_t *millivolts)
{
    uint16_t maximum_raw_value =
        BSPADCGetMaximumRawValue(instance->adc);
    uint16_t reference_millivolts =
        BSPADCGetReferenceMillivolts(instance->adc);
    uint32_t scaled_value;

    if ((maximum_raw_value == 0U) || (reference_millivolts == 0U) ||
        (raw_value > maximum_raw_value)) {
        return false;
    }
    /* 加半个满量程计数后再整除，实现最接近值取整。 */
    scaled_value = ((uint32_t)raw_value * reference_millivolts) +
                   (maximum_raw_value / 2U);
    *millivolts = (uint16_t)(scaled_value / maximum_raw_value);
    return true;
}

static bool ADCIsValid(const ADCInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->device >= ADC_DEVICE_INPUT_0) &&
           (instance->device < ADC_DEVICE_COUNT) &&
           (instance->adc != NULL) && (adc_mutex != NULL);
}

#endif /* ADC/trigger feature set */
