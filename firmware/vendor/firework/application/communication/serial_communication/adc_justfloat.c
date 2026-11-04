/*
 * JustFloat 发送模块只负责“取已完成窗口的尾部样本、打包、发送”三件事。
 * 采样时序由 WaveformMeasurement 管理，串口底层收发由 SerialCommunication 管理。
 */
#include "application/communication/serial_communication/adc_justfloat.h"

#include "application/app_config.h"

#include <stddef.h>
#include <stdint.h>

#if APP_ENABLE_ADC_JUSTFLOAT != 0U
#include <string.h>

#include "FreeRTOS.h"
#include "semphr.h"
#include "task.h"

#include "application/communication/serial_communication/serial_communication.h"
#include "application/task/task_manager.h"
#include "application/waveform/waveform_measurement/waveform_measurement.h"

/* 每个样本按“小端 float + 00 00 80 7F”组成独立 JustFloat 帧。 */
#define ADC_JUSTFLOAT_WAIT_TIMEOUT_MS (100UL)
#define ADC_JUSTFLOAT_SAMPLE_COUNT    (128U)
#define ADC_JUSTFLOAT_VALUE_SIZE      (4U)
#define ADC_JUSTFLOAT_TAIL_SIZE       (4U)
#define ADC_JUSTFLOAT_FRAME_SIZE \
    (ADC_JUSTFLOAT_VALUE_SIZE + ADC_JUSTFLOAT_TAIL_SIZE)
#define ADC_JUSTFLOAT_TX_BUFFER_SIZE \
    (ADC_JUSTFLOAT_SAMPLE_COUNT * ADC_JUSTFLOAT_FRAME_SIZE)

typedef char ADCJustFloatRequires32BitFloat[
    (sizeof(float) == ADC_JUSTFLOAT_VALUE_SIZE) ? 1 : -1];

/*
 * source_mutex 串行化来源切换，短临界区保护任务与回调共享的来源快照；
 * measurement_pending 保证上一窗口尚未发送时不会覆盖保留的 128 点。
 */
static bool adc_justfloat_task_created;
static TaskHandle_t adc_justfloat_task_handle;
static ADCSamplingUART2Source_e adc_justfloat_source =
    (ADCSamplingUART2Source_e)APP_ADC_JUSTFLOAT_DEFAULT_SOURCE;
static ADCSamplingUART2CustomSourceRead_t
    adc_justfloat_custom_source_read;
static void *adc_justfloat_custom_source_context;
static SemaphoreHandle_t adc_justfloat_source_mutex;
static StaticSemaphore_t adc_justfloat_source_mutex_control;
static volatile bool adc_justfloat_measurement_pending;
static uint16_t adc_justfloat_raw_buffer[ADC_JUSTFLOAT_SAMPLE_COUNT];
static float adc_justfloat_value_buffer[ADC_JUSTFLOAT_SAMPLE_COUNT];
static uint8_t adc_justfloat_tx_buffer[ADC_JUSTFLOAT_TX_BUFFER_SIZE];
static const uint8_t adc_justfloat_tail[ADC_JUSTFLOAT_TAIL_SIZE] = {
    0x00U, 0x00U, 0x80U, 0x7FU
};

static void ADCJustFloatTask(void *argument);
static void ADCJustFloatMeasurementReady(
    WaveformMeasurementInput_e input,
    const WaveformMeasurement *measurement, void *context);
static bool ADCJustFloatSourceIsEnabled(
    ADCSamplingUART2Source_e source);
static void ADCJustFloatGetSourceSnapshot(
    ADCSamplingUART2Source_e *source,
    ADCSamplingUART2CustomSourceRead_t *custom_read,
    void **custom_context);
static uint32_t ADCJustFloatSourceLock(void);
static void ADCJustFloatSourceUnlock(uint32_t interrupt_mask);
static bool ADCJustFloatTransactionLock(void);
static void ADCJustFloatTransactionUnlock(void);
static size_t ADCJustFloatBuildFrames(
    const float *samples, size_t sample_count);
#endif

bool ADCJustFloatInit(void)
{
#if APP_ENABLE_ADC_JUSTFLOAT != 0U
    if (!ADCJustFloatTransactionLock()) {
        return false;
    }
    if (adc_justfloat_task_created) {
        bool ready = ADCJustFloatIsReady();

        ADCJustFloatTransactionUnlock();
        return ready;
    }
    if (!ADCJustFloatSourceIsEnabled(adc_justfloat_source) ||
        ((adc_justfloat_source == ADC_SAMPLING_UART2_SOURCE_CUSTOM) &&
            (adc_justfloat_custom_source_read == NULL))) {
        ADCJustFloatTransactionUnlock();
        return false;
    }

    if (!WaveformMeasurementSubscribeResultReady(
            ADCJustFloatMeasurementReady, NULL)) {
        ADCJustFloatTransactionUnlock();
        return false;
    }
    adc_justfloat_task_handle = ApplicationTaskCreate(
        APPLICATION_TASK_ADC_JUSTFLOAT, ADCJustFloatTask, NULL);
    if (adc_justfloat_task_handle == NULL) {
        (void)WaveformMeasurementUnsubscribeResultReady(
            ADCJustFloatMeasurementReady, NULL);
        ADCJustFloatTransactionUnlock();
        return false;
    }
    adc_justfloat_task_created = true;
    ADCJustFloatTransactionUnlock();
    return true;
#else
    return false;
#endif
}

bool ADCJustFloatIsReady(void)
{
#if APP_ENABLE_ADC_JUSTFLOAT != 0U
    ADCSamplingUART2Source_e source;
    ADCSamplingUART2CustomSourceRead_t custom_read;
    void *custom_context;

    ADCJustFloatGetSourceSnapshot(&source, &custom_read, &custom_context);
    (void)custom_context;
    return adc_justfloat_task_created &&
           ADCJustFloatSourceIsEnabled(source) &&
           ((source != ADC_SAMPLING_UART2_SOURCE_CUSTOM) ||
               (custom_read != NULL));
#else
    return false;
#endif
}

bool ADCSamplingUART2SetSource(ADCSamplingUART2Source_e source)
{
#if APP_ENABLE_ADC_JUSTFLOAT != 0U
    uint32_t interrupt_mask;

    if (!ADCJustFloatSourceIsEnabled(source) ||
        !ADCJustFloatTransactionLock()) {
        return false;
    }
    interrupt_mask = ADCJustFloatSourceLock();
    if ((source == ADC_SAMPLING_UART2_SOURCE_CUSTOM) &&
        (adc_justfloat_custom_source_read == NULL)) {
        ADCJustFloatSourceUnlock(interrupt_mask);
        ADCJustFloatTransactionUnlock();
        return false;
    }
    adc_justfloat_source = source;
    adc_justfloat_measurement_pending = false;
    ADCJustFloatSourceUnlock(interrupt_mask);
    if (adc_justfloat_task_handle != NULL) {
        (void)xTaskNotifyGive(adc_justfloat_task_handle);
    }
    ADCJustFloatTransactionUnlock();
    return true;
#else
    (void)source;
    return false;
#endif
}

ADCSamplingUART2Source_e ADCSamplingUART2GetSource(void)
{
#if APP_ENABLE_ADC_JUSTFLOAT != 0U
    ADCSamplingUART2Source_e source;
    uint32_t interrupt_mask = ADCJustFloatSourceLock();

    source = adc_justfloat_source;
    ADCJustFloatSourceUnlock(interrupt_mask);
    return source;
#else
    return ADC_SAMPLING_UART2_SOURCE_COUNT;
#endif
}

bool ADCSamplingUART2SetCustomSource(
    ADCSamplingUART2CustomSourceRead_t read, void *context)
{
#if APP_ENABLE_ADC_JUSTFLOAT != 0U
    uint32_t interrupt_mask;

    if ((read == NULL) || !ADCJustFloatTransactionLock()) {
        return false;
    }
    interrupt_mask = ADCJustFloatSourceLock();
    adc_justfloat_custom_source_read = read;
    adc_justfloat_custom_source_context = context;
    adc_justfloat_source = ADC_SAMPLING_UART2_SOURCE_CUSTOM;
    adc_justfloat_measurement_pending = false;
    ADCJustFloatSourceUnlock(interrupt_mask);
    if (adc_justfloat_task_handle != NULL) {
        (void)xTaskNotifyGive(adc_justfloat_task_handle);
    }
    ADCJustFloatTransactionUnlock();
    return true;
#else
    (void)read;
    (void)context;
    return false;
#endif
}

#if APP_ENABLE_ADC_JUSTFLOAT != 0U
static void ADCJustFloatTask(void *argument)
{
    (void)argument;

    /* 新的采样窗口或自定义数据到达时由通知唤醒；超时后也会重新检查状态。 */
    for (;;) {
        ADCSamplingUART2Source_e source;
        ADCSamplingUART2CustomSourceRead_t custom_read;
        void *custom_context;
        bool measurement_pending = false;
        size_t sample_count = 0U;
        size_t index;

        if (xTaskGetSchedulerState() != taskSCHEDULER_RUNNING) {
            vTaskDelay(1U);
            continue;
        }
        (void)ulTaskNotifyTake(pdTRUE,
            pdMS_TO_TICKS(ADC_JUSTFLOAT_WAIT_TIMEOUT_MS));
        /* 先取得数据源快照，保证本轮处理使用同一套配置。 */
        ADCJustFloatGetSourceSnapshot(
            &source, &custom_read, &custom_context);

        if (source == ADC_SAMPLING_UART2_SOURCE_CUSTOM) {
            /* 自定义源由回调填充浮点数组，任务只负责打包并发送。 */
            if ((custom_read != NULL) &&
                custom_read(adc_justfloat_value_buffer,
                    ADC_JUSTFLOAT_SAMPLE_COUNT, &sample_count,
                    custom_context) &&
                (sample_count > 0U) &&
                (sample_count <= ADC_JUSTFLOAT_SAMPLE_COUNT)) {
                size_t tx_size = ADCJustFloatBuildFrames(
                    adc_justfloat_value_buffer, sample_count);

                if (tx_size > 0U) {
                    (void)SerialCommunicationUART2Send(
                        adc_justfloat_tx_buffer, tx_size);
                }
            }
            continue;
        }

        /* 从测量回调提供的原始缓冲区复制数据，并同时清除待处理标志。 */
        taskENTER_CRITICAL();
        measurement_pending = adc_justfloat_measurement_pending;
        if (measurement_pending) {
            for (index = 0U; index < ADC_JUSTFLOAT_SAMPLE_COUNT; ++index) {
                adc_justfloat_value_buffer[index] =
                    (float)adc_justfloat_raw_buffer[index];
            }
            adc_justfloat_measurement_pending = false;
        }
        taskEXIT_CRITICAL();
        if (!measurement_pending) {
            continue;
        }
        {
            /* JustFloat 每个样本由 4 字节浮点数和固定尾标记组成。 */
            size_t tx_size = ADCJustFloatBuildFrames(
                adc_justfloat_value_buffer,
                ADC_JUSTFLOAT_SAMPLE_COUNT);

            if (tx_size > 0U) {
                (void)SerialCommunicationUART2Send(
                    adc_justfloat_tx_buffer, tx_size);
            }
        }
    }
}

/* 每次完整窗口测量发布后复制最后 128 点，发送任务不再读取实时 DMA 块。 */
static void ADCJustFloatMeasurementReady(
    WaveformMeasurementInput_e input,
    const WaveformMeasurement *measurement, void *context)
{
    ADCSamplingUART2Source_e source;
    WaveformMeasurementInput_e selected_input;
    size_t copied_count;
    size_t offset;

    (void)context;
    if ((measurement == NULL) ||
        (measurement->sample_count < ADC_JUSTFLOAT_SAMPLE_COUNT)) {
        return;
    }
    source = ADCSamplingUART2GetSource();
    if (source == ADC_SAMPLING_UART2_SOURCE_CUSTOM) {
        return;
    }
    selected_input =
        (source == ADC_SAMPLING_UART2_SOURCE_PA21)
            ? WAVEFORM_MEASUREMENT_INPUT_PA21
            : WAVEFORM_MEASUREMENT_INPUT_PA27;
    if (input != selected_input) {
        return;
    }

    taskENTER_CRITICAL();
    if (adc_justfloat_measurement_pending) {
        taskEXIT_CRITICAL();
        return;
    }
    taskEXIT_CRITICAL();
    offset = measurement->sample_count - ADC_JUSTFLOAT_SAMPLE_COUNT;
    if (!WaveformMeasurementCopyLatestInputSamples(input,
            measurement->sequence, offset, adc_justfloat_raw_buffer,
            ADC_JUSTFLOAT_SAMPLE_COUNT, &copied_count) ||
        (copied_count != ADC_JUSTFLOAT_SAMPLE_COUNT)) {
        return;
    }

    taskENTER_CRITICAL();
    adc_justfloat_measurement_pending = true;
    taskEXIT_CRITICAL();
    if (adc_justfloat_task_handle != NULL) {
        (void)xTaskNotifyGive(adc_justfloat_task_handle);
    }
}

static bool ADCJustFloatSourceIsEnabled(
    ADCSamplingUART2Source_e source)
{
    if ((source < ADC_SAMPLING_UART2_SOURCE_PA27) ||
        (source >= ADC_SAMPLING_UART2_SOURCE_COUNT)) {
        return false;
    }
    if (source == ADC_SAMPLING_UART2_SOURCE_PA27) {
        return APP_ENABLE_WAVEFORM_PA27 != 0U;
    }
    if (source == ADC_SAMPLING_UART2_SOURCE_PA21) {
        return APP_ENABLE_WAVEFORM_PA21 != 0U;
    }
    return true;
}

static void ADCJustFloatGetSourceSnapshot(
    ADCSamplingUART2Source_e *source,
    ADCSamplingUART2CustomSourceRead_t *custom_read,
    void **custom_context)
{
    uint32_t interrupt_mask = ADCJustFloatSourceLock();

    *source = adc_justfloat_source;
    *custom_read = adc_justfloat_custom_source_read;
    *custom_context = adc_justfloat_custom_source_context;
    ADCJustFloatSourceUnlock(interrupt_mask);
}

/* 屏蔽中断只覆盖指针和枚举快照，不在该临界区内读取样本或发送串口。 */
static uint32_t ADCJustFloatSourceLock(void)
{
    return portSET_INTERRUPT_MASK_FROM_ISR();
}

static void ADCJustFloatSourceUnlock(uint32_t interrupt_mask)
{
    portCLEAR_INTERRUPT_MASK_FROM_ISR(interrupt_mask);
}

/* 懒创建的静态互斥量保证初始化与运行期来源切换不会交叉提交。 */
static bool ADCJustFloatTransactionLock(void)
{
    if (adc_justfloat_source_mutex == NULL) {
        taskENTER_CRITICAL();
        if (adc_justfloat_source_mutex == NULL) {
            adc_justfloat_source_mutex = xSemaphoreCreateMutexStatic(
                &adc_justfloat_source_mutex_control);
        }
        taskEXIT_CRITICAL();
    }
    return (adc_justfloat_source_mutex != NULL) &&
           (xSemaphoreTake(adc_justfloat_source_mutex,
                portMAX_DELAY) == pdPASS);
}

static void ADCJustFloatTransactionUnlock(void)
{
    (void)xSemaphoreGive(adc_justfloat_source_mutex);
}

/* 将浮点位模式显式拆为小端字节，避免依赖结构体布局或类型别名转换。 */
static size_t ADCJustFloatBuildFrames(
    const float *samples, size_t sample_count)
{
    size_t sample_index;
    size_t tx_index = 0U;

    if ((samples == NULL) ||
        (sample_count > ADC_JUSTFLOAT_SAMPLE_COUNT)) {
        return 0U;
    }
    for (sample_index = 0U; sample_index < sample_count;
         ++sample_index) {
        uint32_t sample_bits;

        memcpy(&sample_bits, &samples[sample_index],
            sizeof(sample_bits));
        adc_justfloat_tx_buffer[tx_index++] =
            (uint8_t)(sample_bits >> 0U);
        adc_justfloat_tx_buffer[tx_index++] =
            (uint8_t)(sample_bits >> 8U);
        adc_justfloat_tx_buffer[tx_index++] =
            (uint8_t)(sample_bits >> 16U);
        adc_justfloat_tx_buffer[tx_index++] =
            (uint8_t)(sample_bits >> 24U);
        memcpy(&adc_justfloat_tx_buffer[tx_index],
            adc_justfloat_tail, sizeof(adc_justfloat_tail));
        tx_index += sizeof(adc_justfloat_tail);
    }
    return tx_index;
}
#endif

/* 遗留兼容空占位：当前函数不执行实际延时，业务代码不得依赖其计时。 */

void delay_ms(uint32_t ms)
{

}
