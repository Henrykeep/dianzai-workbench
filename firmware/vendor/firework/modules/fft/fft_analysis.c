/*
 * FFTAnalysis 管理多输入最新结果、UART 外部频谱发布和可选后台分析任务。
 */
#include "modules/fft/fft_analysis.h"

#include <stddef.h>

#include "FreeRTOS.h"
#include "semphr.h"
#include "task.h"

#include "application/app_config.h"

#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U

#include "modules/fft/fft.h"

#define FFT_ANALYSIS_TASK_PRIORITY   (tskIDLE_PRIORITY + 1U)
/* UART2 FFT 任务需要在栈上保存包含最多16个分量的临时结果。 */
#define FFT_ANALYSIS_TASK_STACK_SIZE \
    (configMINIMAL_STACK_SIZE + 224U)
#define FFT_ANALYSIS_WAIT_TIMEOUT_MS (100UL)
#define FFT_ANALYSIS_ADC_MIDSCALE    (2048)
#define FFT_ANALYSIS_ADC_TO_Q15_SHIFT (4U)
#define FFT_ANALYSIS_RESULT_SUBSCRIBER_COUNT (4U)

static FFTInstance *fft_analysis;
static FFTAnalysisResult
    fft_analysis_results[FFT_ANALYSIS_INPUT_COUNT];
static bool fft_analysis_result_ready[FFT_ANALYSIS_INPUT_COUNT];
static uint32_t
    fft_analysis_result_sequences[FFT_ANALYSIS_INPUT_COUNT];
static SemaphoreHandle_t fft_analysis_mutex;
static StaticSemaphore_t fft_analysis_mutex_control;
/* 二值信号量允许发起 DMA 的菜单任务和完成处理的测量任务跨任务交接。 */
static SemaphoreHandle_t fft_analysis_work_available;
static StaticSemaphore_t fft_analysis_work_available_control;
static bool fft_analysis_adc_capture_reserved;
#if APP_ENABLE_UART2 != 0U
/* UART2 关闭时不为异步帧分析任务及三份 64 点缓冲区预留 SRAM。 */
static bool fft_analysis_task_created;
static StaticTask_t fft_analysis_task_control;
static StackType_t
    fft_analysis_task_stack[FFT_ANALYSIS_TASK_STACK_SIZE];
static int16_t fft_analysis_q15_buffer[FFT_ANALYSIS_UART2_POINT_COUNT];
static int16_t
    fft_analysis_uart2_accumulation[FFT_ANALYSIS_UART2_POINT_COUNT];
static int16_t fft_analysis_uart2_pending[
    FFT_ANALYSIS_UART2_POINT_COUNT];
static size_t fft_analysis_uart2_sample_count;
static uint32_t fft_analysis_uart2_pending_sequence;
static bool fft_analysis_uart2_pending_ready;
static TaskHandle_t fft_analysis_task_handle;
#endif
typedef struct {
    FFTAnalysisResultReadyCallback_t callback;
    void *context;
} FFTAnalysisResultSubscriber;
static FFTAnalysisResultSubscriber fft_analysis_result_subscribers[
    FFT_ANALYSIS_RESULT_SUBSCRIBER_COUNT];

static bool FFTAnalysisInputIsValid(FFTAnalysisInput_e input);
#if APP_ENABLE_UART2 != 0U
static void FFTAnalysisTask(void *argument);
static bool FFTAnalysisCopyUART2PendingFrame(
    uint32_t last_sequence, uint32_t *source_sequence);
#endif
static void FFTAnalysisPublishResult(const FFTResult *result,
    uint32_t sample_rate_hz, uint32_t source_sequence,
    FFTAnalysisInput_e input);

bool FFTAnalysisInit(void)
{
    FFTConfig config;

#if APP_ENABLE_UART2 != 0U
    if ((fft_analysis != NULL) && fft_analysis_task_created) {
#else
    if (fft_analysis != NULL) {
#endif
        return true;
    }

    if (fft_analysis_mutex == NULL) {
        fft_analysis_mutex = xSemaphoreCreateMutexStatic(
            &fft_analysis_mutex_control);
        if (fft_analysis_mutex == NULL) {
            return false;
        }
    }
    if (fft_analysis_work_available == NULL) {
        fft_analysis_work_available = xSemaphoreCreateBinaryStatic(
            &fft_analysis_work_available_control);
        if ((fft_analysis_work_available == NULL) ||
            (xSemaphoreGive(fft_analysis_work_available) != pdPASS)) {
            return false;
        }
    }

    /* 注册工作区时只需合法默认值；ADC 分析会逐次传入实际采样率。 */
    config.sample_rate_hz = 1000000UL;
    config.window         = FFT_WINDOW_HANN;
    config.remove_dc      = APP_FFT_REMOVE_DC != 0U;
    fft_analysis = FFTRegister(&config);
    if ((fft_analysis == NULL) ||
        (FFTGetPointCount(fft_analysis) !=
            FFT_ANALYSIS_MAX_POINT_COUNT)) {
        return false;
    }

#if APP_ENABLE_UART2 != 0U
    if (!fft_analysis_task_created) {
        fft_analysis_task_handle = xTaskCreateStatic(
                FFTAnalysisTask, "FFTAnalysis",
                FFT_ANALYSIS_TASK_STACK_SIZE, NULL,
                FFT_ANALYSIS_TASK_PRIORITY, fft_analysis_task_stack,
                &fft_analysis_task_control);
        if (fft_analysis_task_handle == NULL) {
            return false;
        }
        fft_analysis_task_created = true;
    }
#endif

    return true;
}

bool FFTAnalysisAnalyzeADCSamples(FFTAnalysisInput_e input,
    const uint16_t *samples, size_t sample_count,
    uint32_t sample_rate_hz, uint32_t source_sequence)
{
    FFTResult result;
    bool analyzed;

    if ((input < FFT_ANALYSIS_INPUT_PA27) ||
        (input > FFT_ANALYSIS_INPUT_PA21) || (samples == NULL) ||
        !FFTPointCountIsSupported(sample_count) ||
        (sample_count > FFT_ANALYSIS_MAX_POINT_COUNT) ||
        (sample_rate_hz == 0UL) ||
        (fft_analysis_work_available == NULL) ||
        (xSemaphoreTake(fft_analysis_work_available,
             portMAX_DELAY) != pdPASS)) {
        return false;
    }
    analyzed = FFTAnalyzeUnsignedAtSampleRate(fft_analysis,
        samples, sample_count, FFT_ANALYSIS_ADC_MIDSCALE,
        FFT_ANALYSIS_ADC_TO_Q15_SHIFT, sample_rate_hz, &result);
    (void)xSemaphoreGive(fft_analysis_work_available);
    if (!analyzed) {
        return false;
    }
    FFTAnalysisPublishResult(&result, sample_rate_hz,
        source_sequence, input);
    return true;
}

uint16_t *FFTAnalysisAcquireADCCaptureBuffer(size_t sample_count)
{
    uint16_t *buffer;

    if ((fft_analysis == NULL) ||
        !FFTPointCountIsSupported(sample_count) ||
        (sample_count > FFT_ANALYSIS_MAX_POINT_COUNT) ||
        (fft_analysis_work_available == NULL) ||
        (xSemaphoreTake(fft_analysis_work_available, 0U) != pdPASS)) {
        return NULL;
    }
    buffer = FFTGetUnsignedCaptureBuffer(fft_analysis, sample_count);
    if (buffer == NULL) {
        (void)xSemaphoreGive(fft_analysis_work_available);
    } else {
        taskENTER_CRITICAL();
        fft_analysis_adc_capture_reserved = true;
        taskEXIT_CRITICAL();
    }
    return buffer;
}

bool FFTAnalysisAnalyzeCapturedADCSamples(FFTAnalysisInput_e input,
    size_t sample_count, uint32_t sample_rate_hz,
    uint32_t source_sequence)
{
    FFTResult result;
    uint16_t *samples;
    bool analyzed = false;
    bool capture_reserved;

    taskENTER_CRITICAL();
    capture_reserved = fft_analysis_adc_capture_reserved;
    taskEXIT_CRITICAL();

    if ((input < FFT_ANALYSIS_INPUT_PA27) ||
        (input > FFT_ANALYSIS_INPUT_PA21) ||
        !FFTPointCountIsSupported(sample_count) ||
        (sample_count > FFT_ANALYSIS_MAX_POINT_COUNT) ||
        (sample_rate_hz == 0UL) ||
        (fft_analysis_work_available == NULL) || !capture_reserved) {
        if (capture_reserved) {
            FFTAnalysisReleaseADCCaptureBuffer();
        }
        return false;
    }

    samples = FFTGetUnsignedCaptureBuffer(fft_analysis, sample_count);
    if (samples != NULL) {
        analyzed = FFTAnalyzeUnsignedAtSampleRate(fft_analysis,
            samples, sample_count, FFT_ANALYSIS_ADC_MIDSCALE,
            FFT_ANALYSIS_ADC_TO_Q15_SHIFT, sample_rate_hz, &result);
    }
    FFTAnalysisReleaseADCCaptureBuffer();
    if (!analyzed) {
        return false;
    }
    FFTAnalysisPublishResult(&result, sample_rate_hz,
        source_sequence, input);
    return true;
}

void FFTAnalysisReleaseADCCaptureBuffer(void)
{
    bool release = false;

    taskENTER_CRITICAL();
    if (fft_analysis_adc_capture_reserved) {
        fft_analysis_adc_capture_reserved = false;
        release = true;
    }
    taskEXIT_CRITICAL();
    if (release && (fft_analysis_work_available != NULL)) {
        (void)xSemaphoreGive(fft_analysis_work_available);
    }
}

bool FFTAnalysisCopyLatestResult(FFTAnalysisInput_e input,
    FFTAnalysisResult *result)
{
    if (!FFTAnalysisInputIsValid(input) || (result == NULL) ||
        (fft_analysis_mutex == NULL) ||
        (xSemaphoreTake(fft_analysis_mutex,
             portMAX_DELAY) != pdPASS)) {
        return false;
    }

    if (!fft_analysis_result_ready[input]) {
        (void)xSemaphoreGive(fft_analysis_mutex);
        return false;
    }

    *result = fft_analysis_results[input];
    (void)xSemaphoreGive(fft_analysis_mutex);
    return true;
}

/* 把外部控制器给出的完整频谱压缩为 OLED 共用的 33 个频带并发布。 */
bool FFTAnalysisPublishExternalSpectrum(FFTAnalysisInput_e input,
    const uint32_t *magnitudes, size_t magnitude_count,
    const FFTComponent *components, size_t component_count,
    uint32_t maximum_frequency_hz, uint32_t source_sequence)
{
    FFTAnalysisResult *published_result;
    FFTAnalysisResultSubscriber subscribers[
        FFT_ANALYSIS_RESULT_SUBSCRIBER_COUNT];
    uint32_t maximum_magnitude = 0UL;
    uint32_t scale_maximum;
    size_t peak_index = 1U;
    size_t index;
    size_t bin;

    if ((input != FFT_ANALYSIS_INPUT_UART3) ||
        (magnitudes == NULL) || (magnitude_count < 2U) ||
        (magnitude_count > UINT16_MAX) ||
        ((component_count > 0U) && (components == NULL)) ||
        (component_count > FFT_COMPONENT_MAX_COUNT) ||
        (maximum_frequency_hz == 0UL) ||
        (maximum_frequency_hz > (UINT32_MAX / 2000UL)) ||
        (fft_analysis_mutex == NULL)) {
        return false;
    }

    /* 与本地 FFT 一致：第 0 点视为 DC，主峰只在交流频点中搜索。 */
    for (index = 1U; index < magnitude_count; ++index) {
        if (magnitudes[index] > maximum_magnitude) {
            maximum_magnitude = magnitudes[index];
            peak_index = index;
        }
    }
    if (maximum_magnitude == 0UL) {
        peak_index = 0U;
    }
#if APP_FFT_REMOVE_DC == 0U
    scale_maximum = (magnitudes[0] > maximum_magnitude)
                        ? magnitudes[0]
                        : maximum_magnitude;
#else
    scale_maximum = maximum_magnitude;
#endif

    if (xSemaphoreTake(fft_analysis_mutex, portMAX_DELAY) != pdPASS) {
        return false;
    }
    published_result = &fft_analysis_results[input];
    for (bin = 0U; bin < FFT_ANALYSIS_BIN_COUNT; ++bin) {
        size_t start = (bin == 0U)
                           ? 0U
                           : (1U + (((bin - 1U) *
                                 (magnitude_count - 1U)) /
                                 (FFT_ANALYSIS_BIN_COUNT - 1U)));
        size_t end = (bin == 0U)
                         ? 1U
                         : (1U + ((bin * (magnitude_count - 1U)) /
                               (FFT_ANALYSIS_BIN_COUNT - 1U)));
        uint32_t band_maximum = 0UL;

        if (end <= start) {
            end = start + 1U;
        }
        for (index = start;
             (index < end) && (index < magnitude_count); ++index) {
            if (magnitudes[index] > band_maximum) {
                band_maximum = magnitudes[index];
            }
        }
        published_result->magnitudes[bin] =
            (scale_maximum == 0UL)
                ? 0U
                : (uint16_t)(((uint64_t)band_maximum * UINT16_MAX) /
                      scale_maximum);
    }

    published_result->component_count = (uint8_t)component_count;
    for (index = 0U; index < component_count; ++index) {
        published_result->components[index] = components[index];
    }
    published_result->peak_magnitude =
        (maximum_magnitude == 0UL) ? 0U : UINT16_MAX;
    published_result->peak_bin = (uint16_t)(
        (peak_index * (FFT_ANALYSIS_BIN_COUNT - 1U)) /
        (magnitude_count - 1U));
    published_result->peak_real = 0;
    published_result->peak_imaginary = 0;
    published_result->peak_frequency_millihz = (uint32_t)(
        ((uint64_t)peak_index * maximum_frequency_hz * 1000ULL) /
        (magnitude_count - 1U));
    published_result->sample_rate_hz = maximum_frequency_hz * 2UL;
    published_result->point_count = (uint16_t)magnitude_count;
    published_result->source_sequence = source_sequence;
    published_result->sequence =
        ++fft_analysis_result_sequences[input];
    published_result->input = input;
    fft_analysis_result_ready[input] = true;
    (void)xSemaphoreGive(fft_analysis_mutex);

    taskENTER_CRITICAL();
    for (index = 0U;
         index < FFT_ANALYSIS_RESULT_SUBSCRIBER_COUNT; ++index) {
        subscribers[index] = fft_analysis_result_subscribers[index];
    }
    taskEXIT_CRITICAL();
    for (index = 0U;
         index < FFT_ANALYSIS_RESULT_SUBSCRIBER_COUNT; ++index) {
        if (subscribers[index].callback != NULL) {
            subscribers[index].callback(
                input, source_sequence, subscribers[index].context);
        }
    }
    return true;
}

/* UART2 样本已经是有符号值；每 64 点复制为一帧等待 FFT 任务处理。 */
bool FFTAnalysisSubmitUART2Sample(int16_t sample)
{
#if APP_ENABLE_UART2 != 0U
    size_t index;

    if (!fft_analysis_task_created) {
        return false;
    }

    taskENTER_CRITICAL();
    fft_analysis_uart2_accumulation[
        fft_analysis_uart2_sample_count] = sample;
    ++fft_analysis_uart2_sample_count;

    if (fft_analysis_uart2_sample_count >=
        FFT_ANALYSIS_UART2_POINT_COUNT) {
        for (index = 0U;
             index < FFT_ANALYSIS_UART2_POINT_COUNT; ++index) {
            fft_analysis_uart2_pending[index] =
                fft_analysis_uart2_accumulation[index];
        }
        fft_analysis_uart2_sample_count = 0U;
        ++fft_analysis_uart2_pending_sequence;
        fft_analysis_uart2_pending_ready = true;
    }
    taskEXIT_CRITICAL();
    if (fft_analysis_task_handle != NULL) {
        (void)xTaskNotifyGive(fft_analysis_task_handle);
    }
    return true;
#else
    (void)sample;
    return false;
#endif
}

bool FFTAnalysisIsRunning(void)
{
    return fft_analysis != NULL;
}

bool FFTAnalysisSubscribeResultReady(
    FFTAnalysisResultReadyCallback_t callback, void *context)
{
    size_t index;
    bool result = false;

    if (callback == NULL) {
        return false;
    }
    taskENTER_CRITICAL();
    for (index = 0U;
         index < FFT_ANALYSIS_RESULT_SUBSCRIBER_COUNT; ++index) {
        FFTAnalysisResultSubscriber *subscriber =
            &fft_analysis_result_subscribers[index];

        if ((subscriber->callback == callback) &&
            (subscriber->context == context)) {
            result = true;
            break;
        }
        if (subscriber->callback == NULL) {
            subscriber->context = context;
            subscriber->callback = callback;
            result = true;
            break;
        }
    }
    taskEXIT_CRITICAL();
    return result;
}

bool FFTAnalysisUnsubscribeResultReady(
    FFTAnalysisResultReadyCallback_t callback, void *context)
{
    size_t index;
    bool result = false;

    if (callback == NULL) {
        return false;
    }
    taskENTER_CRITICAL();
    for (index = 0U;
         index < FFT_ANALYSIS_RESULT_SUBSCRIBER_COUNT; ++index) {
        FFTAnalysisResultSubscriber *subscriber =
            &fft_analysis_result_subscribers[index];

        if ((subscriber->callback == callback) &&
            (subscriber->context == context)) {
            subscriber->callback = NULL;
            subscriber->context = NULL;
            result = true;
            break;
        }
    }
    taskEXIT_CRITICAL();
    return result;
}

static bool FFTAnalysisInputIsValid(FFTAnalysisInput_e input)
{
    return (input >= FFT_ANALYSIS_INPUT_PA27) &&
           (input < FFT_ANALYSIS_INPUT_COUNT);
}

/* ADC 由测量应用在收齐自定义点数后同步分析；本任务只处理 UART2 帧。 */
#if APP_ENABLE_UART2 != 0U
static void FFTAnalysisTask(void *argument)
{
    /* 保存最近处理的 UART2 源序列，防止同一帧重复执行 FFT。 */
    uint32_t last_uart2_source_sequence = UINT32_MAX;

    (void)argument;

    /* 本任务只消费 UART2 的异步帧；本地 ADC 的 FFT 由测量任务同步执行。 */
    for (;;) {
        /* 本任务在初始化阶段静态创建，调度器启动前不执行分析。 */
        if (xTaskGetSchedulerState() != taskSCHEDULER_RUNNING) {
            vTaskDelay(1U);
            continue;
        }
        /* UART2 新帧通过任务通知唤醒；超时用于容错并重新检查待处理帧。 */
        (void)ulTaskNotifyTake(pdTRUE,
            pdMS_TO_TICKS(FFT_ANALYSIS_WAIT_TIMEOUT_MS));

        {
            uint32_t source_sequence;
            FFTResult result;
            bool frame_ready;

            /* 将共享待处理帧复制到任务私有缓冲区，缩短临界区时间。 */
            frame_ready = FFTAnalysisCopyUART2PendingFrame(
                last_uart2_source_sequence,
                &source_sequence);
            /*
             * 与 WaveMeasure 的同步 FFT 共用一个计算实例，通过工作互斥锁
             * 保证 CMSIS-DSP 缓冲区和结果不会被并发修改。
             */
            /* 没有新帧或未取得共享工作区时，本轮不发布结果。 */
            if (frame_ready &&
                (fft_analysis_work_available != NULL) &&
                (xSemaphoreTake(fft_analysis_work_available,
                     portMAX_DELAY) == pdPASS)) {
                /* 分析成功后发布结果，并在最后更新序列号完成本帧提交。 */
                if (FFTAnalyzeQ15AtSampleRate(fft_analysis,
                    fft_analysis_q15_buffer,
                    FFT_ANALYSIS_UART2_POINT_COUNT,
                    FFT_ANALYSIS_UART2_SAMPLE_RATE_HZ, &result)) {
                    FFTAnalysisPublishResult(&result,
                        FFT_ANALYSIS_UART2_SAMPLE_RATE_HZ,
                        source_sequence, FFT_ANALYSIS_INPUT_UART2);
                    last_uart2_source_sequence = source_sequence;
                }
                (void)xSemaphoreGive(fft_analysis_work_available);
            }
        }

    }
}

/* 在短临界区内取得 UART2 最新完整 64 点帧。 */
static bool FFTAnalysisCopyUART2PendingFrame(
    uint32_t last_sequence, uint32_t *source_sequence)
{
    size_t index;
    bool result = false;

    if (source_sequence == NULL) {
        return false;
    }

    taskENTER_CRITICAL();
    if (fft_analysis_uart2_pending_ready &&
        (fft_analysis_uart2_pending_sequence != last_sequence)) {
        for (index = 0U;
             index < FFT_ANALYSIS_UART2_POINT_COUNT; ++index) {
            fft_analysis_q15_buffer[index] =
                fft_analysis_uart2_pending[index];
        }
        *source_sequence = fft_analysis_uart2_pending_sequence;
        result = true;
    }
    taskEXIT_CRITICAL();
    return result;
}
#endif

static void FFTAnalysisPublishResult(const FFTResult *result,
    uint32_t sample_rate_hz, uint32_t source_sequence,
    FFTAnalysisInput_e input)
{
    FFTAnalysisResult *published_result;
    size_t bin;
    FFTAnalysisResultSubscriber subscribers[
        FFT_ANALYSIS_RESULT_SUBSCRIBER_COUNT];

    if ((result == NULL) || !FFTAnalysisInputIsValid(input) ||
        (fft_analysis_mutex == NULL) ||
        (xSemaphoreTake(fft_analysis_mutex,
             portMAX_DELAY) != pdPASS)) {
        return;
    }

    published_result = &fft_analysis_results[input];
    for (bin = 0U; bin < FFT_ANALYSIS_BIN_COUNT; ++bin) {
        published_result->magnitudes[bin] =
            result->magnitudes[bin];
    }
    published_result->component_count = result->component_count;
    for (bin = 0U; bin < result->component_count; ++bin) {
        published_result->components[bin] = result->components[bin];
    }
    published_result->peak_magnitude = result->peak_magnitude;
    published_result->peak_bin       = result->peak_bin;
    published_result->peak_real      = result->peak_real;
    published_result->peak_imaginary = result->peak_imaginary;
    published_result->peak_frequency_millihz =
        result->peak_frequency_millihz;
    published_result->sample_rate_hz  = sample_rate_hz;
    published_result->point_count     = result->point_count;
    published_result->source_sequence = source_sequence;
    published_result->sequence =
        ++fft_analysis_result_sequences[input];
    published_result->input = input;
    fft_analysis_result_ready[input] = true;
    (void)xSemaphoreGive(fft_analysis_mutex);

    taskENTER_CRITICAL();
    for (bin = 0U;
         bin < FFT_ANALYSIS_RESULT_SUBSCRIBER_COUNT; ++bin) {
        subscribers[bin] = fft_analysis_result_subscribers[bin];
    }
    taskEXIT_CRITICAL();
    for (bin = 0U;
         bin < FFT_ANALYSIS_RESULT_SUBSCRIBER_COUNT; ++bin) {
        if (subscribers[bin].callback != NULL) {
            subscribers[bin].callback(
                input, source_sequence, subscribers[bin].context);
        }
    }
}

#endif /* APP_ENABLE_WAVEFORM_MEASUREMENT */
