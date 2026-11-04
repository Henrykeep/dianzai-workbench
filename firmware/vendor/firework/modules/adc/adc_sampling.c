/* 为业务层统一两路 ADC 输入映射，并管理异步采集的回调生命周期。 */
#include "modules/adc/adc_sampling.h"

#include "application/app_config.h"

#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U)

#include <stddef.h>

#include "FreeRTOS.h"
#include "semphr.h"

#include "modules/adc/adc.h"

/* 单路直接采集的待调用回调及调用方上下文。 */
typedef struct {
    ADCSamplingDirectCaptureCallback_t callback;
    void *context;
} ADCSamplingDirectCapture;

/* 单路阈值采集的待调用回调及调用方上下文。 */
typedef struct {
    ADCSamplingThresholdCaptureCallback_t callback;
    void *context;
} ADCSamplingThresholdCapture;

/* 每种采集模式只允许同一输入保留一个未结束的回调上下文。 */
static ADCInstance *adc_sampling_inputs[ADC_SAMPLING_INPUT_COUNT];
static ADCSamplingDirectCapture adc_sampling_direct_captures[
    ADC_SAMPLING_INPUT_COUNT];
static ADCSamplingThresholdCapture adc_sampling_threshold_captures[
    ADC_SAMPLING_INPUT_COUNT];
static ADCSamplingSynchronizedCaptureCallback_t
    adc_sampling_synchronized_callback;
static void *adc_sampling_synchronized_context;
static SemaphoreHandle_t adc_sampling_lifecycle_mutex;
static StaticSemaphore_t adc_sampling_lifecycle_mutex_control;

static bool ADCSamplingInputIsValid(ADCSamplingInput_e input);
static bool ADCSamplingLifecycleLock(void);
static void ADCSamplingLifecycleUnlock(void);
static void ADCSamplingHandleDirectCaptureComplete(
    uint32_t sequence, void *context);
static void ADCSamplingHandleThresholdCaptureEvent(
    ADCThresholdEvent_e event, uint32_t sequence, void *context);
static void ADCSamplingHandleSynchronizedCaptureComplete(
    uint32_t sequence, void *context);

/* 输入初始化是幂等操作，并在生命周期锁内完成逻辑输入到 ADC 设备的映射。 */
bool ADCSamplingInitInput(ADCSamplingInput_e input)
{
    ADC_Device_e device;
    bool result;

    if (!ADCSamplingInputIsValid(input) ||
        !ADCSamplingLifecycleLock()) {
        return false;
    }
    if (adc_sampling_inputs[input] == NULL) {
        device = (input == ADC_SAMPLING_INPUT_PA21)
                     ? ADC_DEVICE_INPUT_1
                     : ADC_DEVICE_INPUT_0;
        adc_sampling_inputs[input] = ADCRegister(device);
    }
    result = adc_sampling_inputs[input] != NULL;
    ADCSamplingLifecycleUnlock();
    return result;
}

bool ADCSamplingStartDirectInputCapture(ADCSamplingInput_e input,
    uint16_t *buffer, size_t buffer_capacity, size_t sample_count,
    uint32_t sample_rate_hz,
    ADCSamplingDirectCaptureCallback_t callback, void *context)
{
    ADCInstance *instance;
    bool result;

    if (!ADCSamplingInputIsValid(input) || (buffer == NULL) ||
        (buffer_capacity < sample_count) || (sample_count == 0U) ||
        (sample_rate_hz == 0UL) ||
        (callback == NULL) || !ADCSamplingLifecycleLock()) {
        return false;
    }
    instance = adc_sampling_inputs[input];
    if ((instance == NULL) ||
        (adc_sampling_direct_captures[input].callback != NULL)) {
        ADCSamplingLifecycleUnlock();
        return false;
    }

    /* 先发布上下文再启动硬件，确保极早到达的中断也能找到回调。 */
    adc_sampling_direct_captures[input].context = context;
    adc_sampling_direct_captures[input].callback = callback;
    result = ADCStartDirectCapture(instance, buffer, buffer_capacity,
        sample_count, sample_rate_hz,
        ADCSamplingHandleDirectCaptureComplete,
        (void *)(uintptr_t)input);
    if (!result) {
        adc_sampling_direct_captures[input].callback = NULL;
        adc_sampling_direct_captures[input].context = NULL;
    }
    ADCSamplingLifecycleUnlock();
    return result;
}

bool ADCSamplingStartThresholdInputCapture(ADCSamplingInput_e input,
    uint16_t *buffer, size_t buffer_capacity, size_t sample_count,
    uint32_t sample_rate_hz, uint16_t high_threshold_raw,
    uint16_t low_threshold_raw,
    ADCSamplingThresholdCaptureCallback_t callback, void *context)
{
    ADCInstance *instance;
    bool result;

    if (!ADCSamplingInputIsValid(input) || (buffer == NULL) ||
        (buffer_capacity < sample_count) || (sample_count < 2U) ||
        (sample_rate_hz == 0UL) || (callback == NULL) ||
        !ADCSamplingLifecycleLock()) {
        return false;
    }
    instance = adc_sampling_inputs[input];
    if ((instance == NULL) ||
        (adc_sampling_threshold_captures[input].callback != NULL)) {
        ADCSamplingLifecycleUnlock();
        return false;
    }

    /* 回调上下文保持到调用方显式结束阈值链路，期间可收到采满和重武装事件。 */
    adc_sampling_threshold_captures[input].context = context;
    adc_sampling_threshold_captures[input].callback = callback;
    result = ADCStartThresholdTriggeredCapture(instance, buffer,
        buffer_capacity, sample_count, sample_rate_hz,
        high_threshold_raw, low_threshold_raw,
        ADCSamplingHandleThresholdCaptureEvent,
        (void *)(uintptr_t)input);
    if (!result) {
        adc_sampling_threshold_captures[input].callback = NULL;
        adc_sampling_threshold_captures[input].context = NULL;
    }
    ADCSamplingLifecycleUnlock();
    return result;
}

bool ADCSamplingStartSynchronizedCapture(
    uint16_t *first_buffer, size_t first_buffer_capacity,
    uint16_t *second_buffer, size_t second_buffer_capacity,
    size_t sample_count, uint32_t sample_rate_hz,
    ADCSamplingSynchronizedCaptureCallback_t callback, void *context)
{
    bool result;

    if ((first_buffer == NULL) || (second_buffer == NULL) ||
        (sample_count == 0U) || (callback == NULL) ||
        !ADCSamplingLifecycleLock()) {
        return false;
    }
    if ((adc_sampling_inputs[ADC_SAMPLING_INPUT_PA27] == NULL) ||
        (adc_sampling_inputs[ADC_SAMPLING_INPUT_PA21] == NULL) ||
        (adc_sampling_synchronized_callback != NULL)) {
        ADCSamplingLifecycleUnlock();
        return false;
    }
    /* 双路采集共享一组完成回调，禁止上一事务结束前再次启动。 */
    adc_sampling_synchronized_callback = callback;
    adc_sampling_synchronized_context = context;
    result = ADCStartSynchronizedCapture(
        adc_sampling_inputs[ADC_SAMPLING_INPUT_PA27], first_buffer,
        first_buffer_capacity,
        adc_sampling_inputs[ADC_SAMPLING_INPUT_PA21], second_buffer,
        second_buffer_capacity, sample_count, sample_rate_hz,
        ADCSamplingHandleSynchronizedCaptureComplete, NULL);
    if (!result) {
        adc_sampling_synchronized_callback = NULL;
        adc_sampling_synchronized_context = NULL;
    }
    ADCSamplingLifecycleUnlock();
    return result;
}

bool ADCSamplingFinishSynchronizedCapture(void)
{
    bool result;

    if (!ADCSamplingLifecycleLock()) {
        return false;
    }
    result = ADCFinishSynchronizedCapture();
    if (result) {
        adc_sampling_synchronized_callback = NULL;
        adc_sampling_synchronized_context = NULL;
    }
    ADCSamplingLifecycleUnlock();
    return result;
}

bool ADCSamplingIsSynchronizedCaptureActive(void)
{
    return ADCIsSynchronizedCaptureActive();
}

bool ADCSamplingFinishDirectInputCapture(ADCSamplingInput_e input)
{
    ADCInstance *instance;
    bool result;

    if (!ADCSamplingInputIsValid(input) ||
        !ADCSamplingLifecycleLock()) {
        return false;
    }
    instance = adc_sampling_inputs[input];
    if (instance == NULL) {
        ADCSamplingLifecycleUnlock();
        return true;
    }
    result = ADCFinishDirectCapture(instance);
    if (result) {
        adc_sampling_direct_captures[input].callback = NULL;
        adc_sampling_direct_captures[input].context = NULL;
    }
    ADCSamplingLifecycleUnlock();
    return result;
}

bool ADCSamplingFinishThresholdInputCapture(ADCSamplingInput_e input)
{
    ADCInstance *instance;
    bool result;

    if (!ADCSamplingInputIsValid(input) ||
        !ADCSamplingLifecycleLock()) {
        return false;
    }
    instance = adc_sampling_inputs[input];
    if (instance == NULL) {
        ADCSamplingLifecycleUnlock();
        return true;
    }
    result = ADCFinishThresholdTriggeredCapture(instance);
    if (result) {
        adc_sampling_threshold_captures[input].callback = NULL;
        adc_sampling_threshold_captures[input].context = NULL;
    }
    ADCSamplingLifecycleUnlock();
    return result;
}

bool ADCSamplingConvertRawToMillivolts(ADCSamplingInput_e input,
    uint16_t raw_value, uint16_t *millivolts)
{
    ADCInstance *instance;

    if (!ADCSamplingInputIsValid(input)) {
        return false;
    }
    instance = adc_sampling_inputs[input];
    return (instance != NULL) &&
           ADCConvertRawToMillivolts(instance, raw_value, millivolts);
}

bool ADCSamplingIsDirectInputCaptureActive(ADCSamplingInput_e input)
{
    ADCInstance *instance;

    if (!ADCSamplingInputIsValid(input)) {
        return false;
    }
    instance = adc_sampling_inputs[input];
    return (instance != NULL) && ADCIsDirectCaptureActive(instance);
}

bool ADCSamplingIsThresholdInputCaptureActive(ADCSamplingInput_e input)
{
    ADCInstance *instance;

    if (!ADCSamplingInputIsValid(input)) {
        return false;
    }
    instance = adc_sampling_inputs[input];
    return (instance != NULL) &&
           ADCIsThresholdTriggeredCaptureActive(instance);
}

uint32_t ADCSamplingGetSampleRateHz(void)
{
    ADCSamplingInput_e input;

    for (input = ADC_SAMPLING_INPUT_PA27;
         input < ADC_SAMPLING_INPUT_COUNT; ++input) {
        if (adc_sampling_inputs[input] != NULL) {
            return ADCGetDefaultSampleRateHz(adc_sampling_inputs[input]);
        }
    }
    return 0UL;
}

bool ADCSamplingIsSampleRateSupported(uint32_t sample_rate_hz)
{
    return ADCIsSampleRateSupported(sample_rate_hz);
}

static bool ADCSamplingInputIsValid(ADCSamplingInput_e input)
{
    return (input >= ADC_SAMPLING_INPUT_PA27) &&
           (input < ADC_SAMPLING_INPUT_COUNT);
}

static bool ADCSamplingLifecycleLock(void)
{
    /* 首次使用时在临界区内创建静态互斥锁，避免多任务重复初始化。 */
    if (adc_sampling_lifecycle_mutex == NULL) {
        taskENTER_CRITICAL();
        if (adc_sampling_lifecycle_mutex == NULL) {
            adc_sampling_lifecycle_mutex = xSemaphoreCreateMutexStatic(
                &adc_sampling_lifecycle_mutex_control);
        }
        taskEXIT_CRITICAL();
    }
    return (adc_sampling_lifecycle_mutex != NULL) &&
           (xSemaphoreTake(adc_sampling_lifecycle_mutex,
                portMAX_DELAY) == pdPASS);
}

static void ADCSamplingLifecycleUnlock(void)
{
    (void)xSemaphoreGive(adc_sampling_lifecycle_mutex);
}

static void ADCSamplingHandleDirectCaptureComplete(
    uint32_t sequence, void *context)
{
    ADCSamplingInput_e input =
        (ADCSamplingInput_e)(uintptr_t)context;
    ADCSamplingDirectCaptureCallback_t callback;
    void *callback_context;

    /* context 携带输入编号；本函数在 DMA ISR 中仅转发，不执行生命周期清理。 */
    if (!ADCSamplingInputIsValid(input)) {
        return;
    }
    callback = adc_sampling_direct_captures[input].callback;
    callback_context = adc_sampling_direct_captures[input].context;
    if (callback != NULL) {
        callback(input, sequence, callback_context);
    }
}

static void ADCSamplingHandleThresholdCaptureEvent(
    ADCThresholdEvent_e event, uint32_t sequence, void *context)
{
    ADCSamplingInput_e input =
        (ADCSamplingInput_e)(uintptr_t)context;
    ADCSamplingThresholdCaptureCallback_t callback;
    void *callback_context;
    ADCSamplingThresholdEvent_e sampling_event;

    /* 将底层阈值事件映射为统一事件，保持原采集序号不变。 */
    if (!ADCSamplingInputIsValid(input)) {
        return;
    }
    callback = adc_sampling_threshold_captures[input].callback;
    callback_context = adc_sampling_threshold_captures[input].context;
    sampling_event = (event == ADC_THRESHOLD_SIGNAL_REARMED)
        ? ADC_SAMPLING_THRESHOLD_SIGNAL_REARMED
        : ADC_SAMPLING_THRESHOLD_CAPTURE_COMPLETE;
    if (callback != NULL) {
        callback(input, sampling_event, sequence, callback_context);
    }
}

static void ADCSamplingHandleSynchronizedCaptureComplete(
    uint32_t sequence, void *context)
{
    ADCSamplingSynchronizedCaptureCallback_t callback;
    void *callback_context;

    /* 配对 DMA 均完成后在中断上下文转发同一采集序号。 */
    (void)context;
    callback = adc_sampling_synchronized_callback;
    callback_context = adc_sampling_synchronized_context;
    if (callback != NULL) {
        callback(sequence, callback_context);
    }
}

#endif /* ADC/trigger feature set */
