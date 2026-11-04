/*
 * 波形测量层是“采样窗口 -> 参数/FFT/相位结果”的流水线。
 * 采集回调只推进数据状态，计算和订阅通知在任务上下文执行，避免把重计算放进 ISR。
 */
#include "application/waveform/waveform_measurement/waveform_measurement.h"

#include "application/app_config.h"

#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U

#include <stddef.h>

#include "FreeRTOS.h"
#include "semphr.h"
#include "task.h"

#include "arm_math.h"

#include "application/communication/serial_communication/serial_communication.h"
#include "application/task/task_manager.h"
#if (APP_ENABLE_WAVEFORM_MAPPING != 0U) && \
    (APP_WAVEFORM_MAPPING_BACKEND_DAC != 0U)
#include "application/waveform/waveform_output/waveform_output.h"
#endif
#include "modules/adc/adc_sampling.h"
#include "modules/capture/analog_capture.h"
#include "modules/fft/fft_analysis.h"

/* 任务唤醒、时域统计和轻量波形分类使用的定点比例及判定阈值。 */
#define WAVEFORM_MEASUREMENT_WAIT_TIMEOUT_MS (100UL)
#define WAVEFORM_MEASUREMENT_DUTY_SCALE     (10000UL)
#define WAVEFORM_MEASUREMENT_MINIMUM_P2P_RAW (8U)
#define WAVEFORM_MEASUREMENT_CLASSIFY_SCALE (10000UL)
#define WAVEFORM_MEASUREMENT_CLASSIFY_RAIL_MARGIN (1000UL)
#define WAVEFORM_MEASUREMENT_CLASSIFY_SQUARE_RAIL_MINIMUM (7000UL)
#define WAVEFORM_MEASUREMENT_CLASSIFY_SQUARE_SIDE_MINIMUM (500UL)
#define WAVEFORM_MEASUREMENT_CLASSIFY_SQUARE_CREST_SQUARED_MAXIMUM \
    (13500UL)
#define WAVEFORM_MEASUREMENT_CLASSIFY_SINE_RAIL_MINIMUM (3000UL)
#define WAVEFORM_MEASUREMENT_CLASSIFY_SINE_RAIL_CREST_SQUARED_MAXIMUM \
    (27000UL)
#define WAVEFORM_MEASUREMENT_CLASSIFY_SPECTRAL_MINIMUM (5500UL)
#define WAVEFORM_MEASUREMENT_CLASSIFY_SINE_CREST_SQUARED_MINIMUM (14000UL)
#define WAVEFORM_MEASUREMENT_CLASSIFY_SINE_CREST_SQUARED_MAXIMUM (24500UL)
#define WAVEFORM_MEASUREMENT_CLASSIFY_TRIANGLE_CREST_SQUARED_MAXIMUM (40000UL)
#define WAVEFORM_MEASUREMENT_CLASSIFY_TRIANGLE_STEP_UNIFORMITY_MAXIMUM \
    (14000UL)
#define WAVEFORM_MEASUREMENT_CLASSIFY_TRIANGLE_THIRD_HARMONIC_MINIMUM \
    (500UL)
#define WAVEFORM_MEASUREMENT_CLASSIFY_TRIANGLE_CURVATURE_FACTOR \
    (54000UL)
#define WAVEFORM_MEASUREMENT_CLASSIFY_TRIANGLE_CURVATURE_MINIMUM_BIN \
    (16U)
#define WAVEFORM_MEASUREMENT_CLASSIFY_TRIANGLE_CURVATURE_MINIMUM_SAMPLES \
    (5U)
#define WAVEFORM_MEASUREMENT_CLASSIFY_SAWTOOTH_JUMP_FACTOR (4UL)
/* Capture 新鲜度、FFT 一致性和整次 DMA 请求的两级超时约束。 */
#define WAVEFORM_MEASUREMENT_CAPTURE_TIMEOUT_PERIODS (3UL)
#define WAVEFORM_MEASUREMENT_CAPTURE_MINIMUM_TIMEOUT_MS (250UL)
#define WAVEFORM_MEASUREMENT_CAPTURE_FFT_MINIMUM_RELIABLE_BIN (8U)
#define WAVEFORM_MEASUREMENT_CAPTURE_FFT_TOLERANCE_BINS (2UL)
#define WAVEFORM_MEASUREMENT_CAPTURE_FFT_TOLERANCE_PERMYRIAD (200UL)
#define WAVEFORM_MEASUREMENT_REQUEST_TIMEOUT_MARGIN_MS (1000UL)
#define WAVEFORM_MEASUREMENT_REQUEST_STALL_TIMEOUT_MS (1500UL)
#define WAVEFORM_MEASUREMENT_REQUEST_MAXIMUM_MULTIPLIER (8ULL)
/* 结果订阅容量、页面保留点数及双路相位计算的定点常量。 */
#define WAVEFORM_MEASUREMENT_DEBUG_OUTPUT_ENABLED (1U)
#define WAVEFORM_MEASUREMENT_RESULT_SUBSCRIBER_COUNT (4U)
#define WAVEFORM_MEASUREMENT_RETAINED_SAMPLE_COUNT (128U)
#define WAVEFORM_MEASUREMENT_PHASE_MINIMUM_PEAK_MAGNITUDE (16U)
#define WAVEFORM_MEASUREMENT_PHASE_FREQUENCY_TOLERANCE_BINS (1ULL)
#define WAVEFORM_MEASUREMENT_PI_Q29 (1686629713LL)
/*
 * 除默认兼容输入外，下列数组均以 WaveformMeasurementInput_e 为下标；
 * 请求状态由 API、DMA ISR 和测量任务共享，结果与订阅表由互斥量保护。
 */
static WaveformMeasurementInput_e waveform_measurement_input =
#if APP_ENABLE_WAVEFORM_PA27 != 0U
    WAVEFORM_MEASUREMENT_INPUT_PA27;
#else
    WAVEFORM_MEASUREMENT_INPUT_PA21;
#endif
WaveformMeasurement waveform_measurement_results[
    WAVEFORM_MEASUREMENT_INPUT_COUNT];
static bool waveform_measurement_result_ready[
    WAVEFORM_MEASUREMENT_INPUT_COUNT];
static volatile bool waveform_measurement_request_pending[
    WAVEFORM_MEASUREMENT_INPUT_COUNT];
volatile WaveformMeasurementRequestStatus_e
    waveform_measurement_request_statuses[
        WAVEFORM_MEASUREMENT_INPUT_COUNT];
static TickType_t waveform_measurement_request_start_ticks[
    WAVEFORM_MEASUREMENT_INPUT_COUNT];
volatile uint32_t waveform_measurement_last_progress_ticks[
    WAVEFORM_MEASUREMENT_INPUT_COUNT];
volatile uint32_t waveform_measurement_accepted_block_counts[
    WAVEFORM_MEASUREMENT_INPUT_COUNT];
volatile uint32_t waveform_measurement_rejected_block_counts[
    WAVEFORM_MEASUREMENT_INPUT_COUNT];
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
volatile WaveformSynchronizedPhaseMeasurement
    waveform_measurement_synchronized_phase_result;
#endif
static volatile uint32_t waveform_measurement_request_source_sequences[
    WAVEFORM_MEASUREMENT_INPUT_COUNT] = {
        UINT32_MAX, UINT32_MAX
    };
static bool waveform_measurement_task_created;
static uint32_t waveform_measurement_result_sequences[
    WAVEFORM_MEASUREMENT_INPUT_COUNT];
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
static uint32_t waveform_measurement_synchronized_phase_sequence;
#endif
static SemaphoreHandle_t waveform_measurement_mutex;
static StaticSemaphore_t waveform_measurement_mutex_control;
#if APP_ENABLE_WAVEFORM_PA27 != 0U
static uint16_t waveform_measurement_pa27_retained_samples[
    WAVEFORM_MEASUREMENT_RETAINED_SAMPLE_COUNT];
#endif
#if APP_ENABLE_WAVEFORM_PA21 != 0U
static uint16_t waveform_measurement_pa21_retained_samples[
    WAVEFORM_MEASUREMENT_RETAINED_SAMPLE_COUNT];
#endif
static uint16_t waveform_measurement_retained_staging[
    WAVEFORM_MEASUREMENT_RETAINED_SAMPLE_COUNT];
/* DMA 期间指向 FFT 复数工作区；FFT 开始后原始内容会被原地覆盖。 */
static uint16_t *waveform_measurement_capture_samples[
    WAVEFORM_MEASUREMENT_INPUT_COUNT];
static bool waveform_measurement_fft_workspace_reserved[
    WAVEFORM_MEASUREMENT_INPUT_COUNT];
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE != 0U
/*
 * 同步 DMA 的 PA27 使用既有 FFT 工作区；PA21 需要独立缓冲区才能在同一
 * 个触发窗口内保留两路原始数据。两路随后在测量任务中依次进行 FFT。
 */
static uint16_t waveform_measurement_synchronized_pa21_samples[
    APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT];
static volatile bool waveform_measurement_synchronized_request_active;
#endif
static volatile size_t waveform_measurement_collected_sample_counts[
    WAVEFORM_MEASUREMENT_INPUT_COUNT];
static bool waveform_measurement_initializing;
static TaskHandle_t waveform_measurement_task_handle;

/* 一项订阅由回调和上下文共同标识，发布前会整体复制到任务栈后锁外调用。 */
typedef struct {
    WaveformMeasurementResultReadyCallback_t callback;
    void *context;
} WaveformMeasurementResultSubscriber;

/* FFT 覆盖原始样本前提取的全部时域统计量。 */
typedef struct {
    uint16_t minimum_raw;
    uint16_t maximum_raw;
    uint16_t average_raw;
    uint32_t high_sample_count;
    uint32_t low_rail_count;
    uint32_t high_rail_count;
    uint32_t peak_deviation;
    uint32_t maximum_step;
    uint64_t sum_squared;
    uint64_t sum_absolute_steps;
    uint64_t sum_squared_steps;
    uint64_t sum_absolute_second_differences;
} WaveformMeasurementTimeFeatures;

/* 相位计算只需保留每路主峰复数向量，不额外常驻整帧采样数据。 */
typedef struct {
    int16_t peak_real;
    int16_t peak_imaginary;
    uint16_t peak_magnitude;
    uint16_t peak_bin;
    uint16_t point_count;
    uint32_t peak_frequency_millihz;
    uint32_t sample_rate_hz;
    uint32_t source_sequence;
    bool ready;
} WaveformMeasurementPhaseFFTFrame;

#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
static WaveformMeasurementPhaseFFTFrame
    waveform_measurement_phase_fft_frames[
        WAVEFORM_MEASUREMENT_INPUT_COUNT];
#endif

static WaveformMeasurementResultSubscriber
    waveform_measurement_result_subscribers[
        WAVEFORM_MEASUREMENT_RESULT_SUBSCRIBER_COUNT];

static void WaveformMeasurementTask(void *argument);
static bool WaveformMeasurementInputIsValid(
    WaveformMeasurementInput_e input);
static bool WaveformMeasurementInputConfigIsValid(
    WaveformMeasurementInput_e input);
static TickType_t WaveformMeasurementGetRequestTimeoutTicks(
    WaveformMeasurementInput_e input);
static bool WaveformMeasurementRequestHasTimedOut(
    WaveformMeasurementInput_e input, TickType_t current_time);
static uint16_t *WaveformMeasurementGetSampleBuffer(
    WaveformMeasurementInput_e input);
static uint16_t *WaveformMeasurementGetRetainedSampleBuffer(
    WaveformMeasurementInput_e input);
static bool WaveformMeasurementExtractTimeFeatures(
    const uint16_t *samples, size_t sample_count,
    WaveformMeasurementTimeFeatures *features);
static void WaveformMeasurementRetainSamples(
    WaveformMeasurementInput_e input,
    const uint16_t *samples, size_t sample_count);
static void WaveformMeasurementCommitRetainedSamples(
    WaveformMeasurementInput_e input, size_t sample_count);
static void WaveformMeasurementReleaseFFTWorkspace(
    WaveformMeasurementInput_e input);
static ADCSamplingInput_e WaveformMeasurementMapADCInput(
    WaveformMeasurementInput_e input);
static FFTAnalysisInput_e WaveformMeasurementMapFFTInput(
    WaveformMeasurementInput_e input);
static AnalogCaptureInput_e WaveformMeasurementMapCaptureInput(
    WaveformMeasurementInput_e input);
static bool WaveformMeasurementCalculate(
    WaveformMeasurementInput_e input,
    const WaveformMeasurementTimeFeatures *features,
    size_t sample_count,
    uint32_t sample_rate_hz,
    const FFTAnalysisResult *fft_result,
    const AnalogCaptureMeasurement *capture_result,
    WaveformMeasurement *measurement);
static WaveformMeasurementWaveformType_e
    WaveformMeasurementClassifyWaveform(
        const WaveformMeasurementTimeFeatures *features,
        size_t sample_count,
        const FFTAnalysisResult *fft_result);
static bool WaveformMeasurementCaptureIsFresh(
    const AnalogCaptureMeasurement *capture_result,
    TickType_t update_time, TickType_t current_time);
static bool WaveformMeasurementCaptureMatchesFFT(
    const AnalogCaptureMeasurement *capture_result,
    const FFTAnalysisResult *fft_result);
static void WaveformMeasurementPublish(
    const WaveformMeasurement *measurement,
    WaveformMeasurementInput_e input);
static void WaveformMeasurementUpdatePhaseFFTFrame(
    WaveformMeasurementInput_e input,
    const FFTAnalysisResult *fft_result);
static void WaveformMeasurementTryPublishSynchronizedPhase(
    uint32_t source_sequence);
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
static int32_t WaveformMeasurementSaturateQ31(int64_t value);
static int32_t WaveformMeasurementWrapPhaseMillidegrees(
    int32_t phase_millidegrees);
#endif
static void WaveformMeasurementDebugSend(
    const uint8_t *data, size_t size);
static bool WaveformMeasurementInitInputs(void);
static void WaveformMeasurementRollbackInputs(void);
static void WaveformMeasurementStopMeasurementInputs(void);
static void WaveformMeasurementCompleteRequest(
    WaveformMeasurementInput_e input);
static void WaveformMeasurementADCDirectCaptureCompleteFromISR(
    ADCSamplingInput_e input, uint32_t source_sequence,
    void *context);
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE != 0U
static bool WaveformMeasurementRequestSynchronized(
    WaveformMeasurementInput_e requested_input);
static void WaveformMeasurementADCSynchronizedCaptureCompleteFromISR(
    uint32_t source_sequence, void *context);
#endif
#if APP_ENABLE_UART2 != 0U
static void WaveformMeasurementUART2SampleReceived(
    int16_t sample, void *context);
#endif

bool WaveformMeasurementInit(void)
{
    static const uint8_t init_message[] =
        "WAVEFORM MEASUREMENT INIT\r\n";
    static const uint8_t error_message[] =
        "WAVEFORM MEASUREMENT ERROR\r\n";
#if (APP_ENABLE_WAVEFORM_PA27 != 0U) && \
    (APP_ENABLE_WAVEFORM_PA21 != 0U)
    static const uint8_t ready_message[] =
        "WAVEFORM MEASUREMENT READY PA27 PA21\r\n";
#elif APP_ENABLE_WAVEFORM_PA27 != 0U
    static const uint8_t ready_message[] =
        "WAVEFORM MEASUREMENT READY PA27\r\n";
#elif APP_ENABLE_WAVEFORM_PA21 != 0U
    static const uint8_t ready_message[] =
        "WAVEFORM MEASUREMENT READY PA21\r\n";
#else
    static const uint8_t ready_message[] =
        "WAVEFORM MEASUREMENT READY\r\n";
#endif
    if (waveform_measurement_task_created) {
        return true;
    }
    if (waveform_measurement_initializing) {
        return false;
    }
    waveform_measurement_initializing = true;

    WaveformMeasurementDebugSend(
        init_message, sizeof(init_message) - 1U);
    if (!WaveformMeasurementInitInputs() ||
#if APP_ENABLE_WAVEFORM_PA27 != 0U
        !WaveformMeasurementInputConfigIsValid(
            WAVEFORM_MEASUREMENT_INPUT_PA27) ||
#endif
#if APP_ENABLE_WAVEFORM_PA21 != 0U
        !WaveformMeasurementInputConfigIsValid(
            WAVEFORM_MEASUREMENT_INPUT_PA21) ||
#endif
        !FFTAnalysisInit()) {
        WaveformMeasurementRollbackInputs();
        WaveformMeasurementDebugSend(
            error_message, sizeof(error_message) - 1U);
        waveform_measurement_initializing = false;
        return false;
    }

    if (waveform_measurement_mutex == NULL) {
        waveform_measurement_mutex = xSemaphoreCreateMutexStatic(
            &waveform_measurement_mutex_control);
        if (waveform_measurement_mutex == NULL) {
            WaveformMeasurementDebugSend(
                error_message, sizeof(error_message) - 1U);
            WaveformMeasurementRollbackInputs();
            waveform_measurement_initializing = false;
            return false;
        }
    }

#if APP_ENABLE_UART2 != 0U
    if (!SerialCommunicationUART2SubscribeSample(
            WaveformMeasurementUART2SampleReceived, NULL)) {
        WaveformMeasurementRollbackInputs();
        WaveformMeasurementDebugSend(
            error_message, sizeof(error_message) - 1U);
        waveform_measurement_initializing = false;
        return false;
    }
#endif

    waveform_measurement_task_handle = ApplicationTaskCreate(
            APPLICATION_TASK_WAVEFORM_MEASUREMENT,
            WaveformMeasurementTask, NULL);
    if (waveform_measurement_task_handle == NULL) {
        WaveformMeasurementDebugSend(
            error_message, sizeof(error_message) - 1U);
        WaveformMeasurementRollbackInputs();
#if APP_ENABLE_UART2 != 0U
        (void)SerialCommunicationUART2UnsubscribeSample(
            WaveformMeasurementUART2SampleReceived, NULL);
#endif
        waveform_measurement_initializing = false;
        return false;
    }

    waveform_measurement_task_created = true;
    /* 初始化只准备资源；实际采样由菜单或公开请求接口按次启动。 */
    WaveformMeasurementStopMeasurementInputs();
    waveform_measurement_initializing = false;
    WaveformMeasurementDebugSend(
        ready_message, sizeof(ready_message) - 1U);
    return true;
}

/* 只注册当前工程启用的统一波形输入及其 COMP 捕获链路。 */
static bool WaveformMeasurementInitInputs(void)
{
#if APP_ENABLE_WAVEFORM_PA27 != 0U
    if (!ADCSamplingInitInput(ADC_SAMPLING_INPUT_PA27) ||
        !AnalogCaptureInitInput(ANALOG_CAPTURE_INPUT_PA27)) {
        return false;
    }
#endif
#if APP_ENABLE_WAVEFORM_PA21 != 0U
    if (!ADCSamplingInitInput(ADC_SAMPLING_INPUT_PA21) ||
        !AnalogCaptureInitInput(ANALOG_CAPTURE_INPUT_PA21)) {
        return false;
    }
#endif
    return true;
}

/* 初始化中途失败时逆向释放已启动的 ADC 和 Capture，不销毁静态资源。 */
static void WaveformMeasurementRollbackInputs(void)
{
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE != 0U
    (void)ADCSamplingFinishSynchronizedCapture();
    waveform_measurement_synchronized_request_active = false;
#endif
#if APP_ENABLE_WAVEFORM_PA21 != 0U
    if (AnalogCaptureIsInputRunning(ANALOG_CAPTURE_INPUT_PA21)) {
        (void)AnalogCaptureStopInput(ANALOG_CAPTURE_INPUT_PA21);
    }
    (void)ADCSamplingFinishDirectInputCapture(
        ADC_SAMPLING_INPUT_PA21);
#endif
#if APP_ENABLE_WAVEFORM_PA27 != 0U
    if (AnalogCaptureIsInputRunning(ANALOG_CAPTURE_INPUT_PA27)) {
        (void)AnalogCaptureStopInput(ANALOG_CAPTURE_INPUT_PA27);
    }
    (void)ADCSamplingFinishDirectInputCapture(
        ADC_SAMPLING_INPUT_PA27);
#endif
}

/* 保留注册和任务资源；初始化结束后确保没有一次性采集仍占用硬件。 */
static void WaveformMeasurementStopMeasurementInputs(void)
{
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE != 0U
    (void)ADCSamplingFinishSynchronizedCapture();
    waveform_measurement_synchronized_request_active = false;
#endif
#if APP_ENABLE_WAVEFORM_PA21 != 0U
    if (AnalogCaptureIsInputRunning(ANALOG_CAPTURE_INPUT_PA21)) {
        (void)AnalogCaptureStopInput(ANALOG_CAPTURE_INPUT_PA21);
    }
    (void)ADCSamplingFinishDirectInputCapture(
        ADC_SAMPLING_INPUT_PA21);
#endif
#if APP_ENABLE_WAVEFORM_PA27 != 0U
    if (AnalogCaptureIsInputRunning(ANALOG_CAPTURE_INPUT_PA27)) {
        (void)AnalogCaptureStopInput(ANALOG_CAPTURE_INPUT_PA27);
    }
    (void)ADCSamplingFinishDirectInputCapture(
        ADC_SAMPLING_INPUT_PA27);
#endif
}

bool WaveformMeasurementIsInputEnabled(
    WaveformMeasurementInput_e input)
{
    if (!WaveformMeasurementInputIsValid(input)) {
        return false;
    }

    if (input == WAVEFORM_MEASUREMENT_INPUT_PA27) {
        return APP_ENABLE_WAVEFORM_PA27 != 0U;
    }
    return APP_ENABLE_WAVEFORM_PA21 != 0U;
}

bool WaveformMeasurementRequestInput(
    WaveformMeasurementInput_e input)
{
    ADCSamplingInput_e adc_input;
    AnalogCaptureInput_e capture_input;
    bool capture_started = false;
    uint16_t *measurement_samples;

    if (!waveform_measurement_task_created ||
        !WaveformMeasurementInputIsValid(input) ||
        !WaveformMeasurementIsInputEnabled(input)) {
        return false;
    }

#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE != 0U
    /* 同步模式下任意一路请求都会由同一触发时钟采满 PA27 和 PA21。 */
    return WaveformMeasurementRequestSynchronized(input);
#endif

    if ((waveform_measurement_mutex == NULL) ||
        (xSemaphoreTake(waveform_measurement_mutex,
             portMAX_DELAY) != pdPASS)) {
        return false;
    }

    if (waveform_measurement_request_pending[input]) {
        (void)xSemaphoreGive(waveform_measurement_mutex);
        return false;
    }
    adc_input = WaveformMeasurementMapADCInput(input);
    waveform_measurement_request_source_sequences[input] = UINT32_MAX;
    waveform_measurement_collected_sample_counts[input] = 0U;
    waveform_measurement_request_start_ticks[input] =
        xTaskGetTickCount();
    waveform_measurement_last_progress_ticks[input] =
        (uint32_t)waveform_measurement_request_start_ticks[input];
    waveform_measurement_accepted_block_counts[input] = 0UL;
    waveform_measurement_rejected_block_counts[input] = 0UL;
    waveform_measurement_request_statuses[input] =
        WAVEFORM_MEASUREMENT_REQUEST_COLLECTING;
    /* 先占用请求槽，随后直接启动一次完整 N 点 DMA。 */
    waveform_measurement_request_pending[input] = true;
    (void)xSemaphoreGive(waveform_measurement_mutex);

#if (APP_ENABLE_WAVEFORM_MAPPING != 0U) && \
    (APP_WAVEFORM_MAPPING_BACKEND_DAC != 0U)
    /*
     * PA27 映射结果会驱动 PA15 DAC。开始下一次 PA27 采样前先停止
     * DAC 及其循环 DMA，避免其占用总线或通过模拟电源/地耦合干扰 ADC。
     * 本次测量成功发布后，原有 Mapping 回调会按新结果重新启动 DAC。
     */
    if (input == WAVEFORM_MEASUREMENT_INPUT_PA27) {
        (void)WaveformOutputDACStop();
    }
#endif

    /*
     * 先独占 FFT 工作区，再把其起始区域交给 ADC DMA。这样无需为 PA27、
     * PA21 另外常驻一份 2～4 KB 原始采样数组。
     */
    measurement_samples = FFTAnalysisAcquireADCCaptureBuffer(
        WaveformMeasurementGetInputSampleCount(input));
    if (measurement_samples != NULL) {
        waveform_measurement_capture_samples[input] = measurement_samples;
        waveform_measurement_fft_workspace_reserved[input] = true;
    }
    capture_input = WaveformMeasurementMapCaptureInput(input);
    capture_started = (measurement_samples != NULL) &&
        AnalogCaptureStartInput(capture_input);
    if (!capture_started || (measurement_samples == NULL)) {
        if (capture_started) {
            (void)AnalogCaptureStopInput(capture_input);
        }
        WaveformMeasurementReleaseFFTWorkspace(input);
        if (xSemaphoreTake(waveform_measurement_mutex,
                portMAX_DELAY) == pdPASS) {
            waveform_measurement_request_pending[input] = false;
            waveform_measurement_request_statuses[input] =
                WAVEFORM_MEASUREMENT_REQUEST_START_FAILED;
            (void)xSemaphoreGive(waveform_measurement_mutex);
        }
        return false;
    }

    /* PA27、PA21 都只使用一次性 N 点 DMA，不再建立 64 点流式链路。 */
    if (xSemaphoreTake(waveform_measurement_mutex,
            portMAX_DELAY) != pdPASS) {
        taskENTER_CRITICAL();
        waveform_measurement_request_pending[input] = false;
        waveform_measurement_request_statuses[input] =
            WAVEFORM_MEASUREMENT_REQUEST_START_FAILED;
        taskEXIT_CRITICAL();
        (void)AnalogCaptureStopInput(capture_input);
        WaveformMeasurementReleaseFFTWorkspace(input);
        return false;
    }
    waveform_measurement_request_source_sequences[input] = UINT32_MAX;
    waveform_measurement_collected_sample_counts[input] = 0U;
    waveform_measurement_request_start_ticks[input] =
        xTaskGetTickCount();
    waveform_measurement_last_progress_ticks[input] =
        (uint32_t)waveform_measurement_request_start_ticks[input];
    (void)xSemaphoreGive(waveform_measurement_mutex);

    if (!ADCSamplingStartDirectInputCapture(adc_input,
            measurement_samples,
            FFT_ANALYSIS_ADC_CAPTURE_BUFFER_CAPACITY,
            WaveformMeasurementGetInputSampleCount(input),
            WaveformMeasurementGetInputSampleRateHz(input),
            WaveformMeasurementADCDirectCaptureCompleteFromISR,
            NULL)) {
        (void)ADCSamplingFinishDirectInputCapture(adc_input);
        (void)AnalogCaptureStopInput(capture_input);
        WaveformMeasurementReleaseFFTWorkspace(input);
        if (xSemaphoreTake(waveform_measurement_mutex,
                portMAX_DELAY) == pdPASS) {
            waveform_measurement_request_pending[input] = false;
            waveform_measurement_request_statuses[input] =
                WAVEFORM_MEASUREMENT_REQUEST_START_FAILED;
            (void)xSemaphoreGive(waveform_measurement_mutex);
        }
        return false;
    }
    return true;
}

bool WaveformMeasurementRequestSynchronizedPhase(void)
{
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
    if (!WaveformMeasurementIsInputEnabled(
            WAVEFORM_MEASUREMENT_INPUT_PA27) ||
        !WaveformMeasurementIsInputEnabled(
            WAVEFORM_MEASUREMENT_INPUT_PB19)) {
        return false;
    }
    return WaveformMeasurementRequestInput(
        WAVEFORM_MEASUREMENT_INPUT_PA27);
#else
    return false;
#endif
}

bool WaveformMeasurementCopyLatestSynchronizedPhase(
    WaveformSynchronizedPhaseMeasurement *measurement)
{
    if ((measurement == NULL) ||
        (waveform_measurement_mutex == NULL) ||
        (xSemaphoreTake(waveform_measurement_mutex,
             portMAX_DELAY) != pdPASS)) {
        return false;
    }
    if (waveform_measurement_synchronized_phase_result.status ==
        WAVEFORM_SYNCHRONIZED_PHASE_STATUS_NOT_READY) {
        (void)xSemaphoreGive(waveform_measurement_mutex);
        return false;
    }
    *measurement = waveform_measurement_synchronized_phase_result;
    (void)xSemaphoreGive(waveform_measurement_mutex);
    return true;
}

#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE != 0U
/*
 * 使用同一 TIMG0 触发窗口同时采集 PA27/PA21。
 *
 * PA27 缓冲区复用 FFT 工作区，PA21 使用专用 DMA 缓冲区；两路都标记为
 * pending，完成回调会把相同的序列号和采样点数交给测量任务分别处理。
 */
static bool WaveformMeasurementRequestSynchronized(
    WaveformMeasurementInput_e requested_input)
{
    uint16_t *pa27_samples;
    TickType_t start_tick;
    bool pa27_capture_started = false;
    bool pa21_capture_started = false;

    if ((waveform_measurement_mutex == NULL) ||
        (xSemaphoreTake(waveform_measurement_mutex,
             portMAX_DELAY) != pdPASS)) {
        return false;
    }
    if (waveform_measurement_synchronized_request_active ||
        waveform_measurement_request_pending[
            WAVEFORM_MEASUREMENT_INPUT_PA27] ||
        waveform_measurement_request_pending[
            WAVEFORM_MEASUREMENT_INPUT_PA21]) {
        (void)xSemaphoreGive(waveform_measurement_mutex);
        return false;
    }

    start_tick = xTaskGetTickCount();
    waveform_measurement_input = requested_input;
    for (WaveformMeasurementInput_e input =
             WAVEFORM_MEASUREMENT_INPUT_PA27;
         input < WAVEFORM_MEASUREMENT_INPUT_COUNT; ++input) {
        waveform_measurement_request_pending[input] = true;
        waveform_measurement_request_source_sequences[input] = UINT32_MAX;
        waveform_measurement_collected_sample_counts[input] = 0U;
        waveform_measurement_request_start_ticks[input] = start_tick;
        waveform_measurement_last_progress_ticks[input] =
            (uint32_t)start_tick;
        waveform_measurement_accepted_block_counts[input] = 0UL;
        waveform_measurement_rejected_block_counts[input] = 0UL;
        waveform_measurement_request_statuses[input] =
            WAVEFORM_MEASUREMENT_REQUEST_COLLECTING;
    }
    (void)xSemaphoreGive(waveform_measurement_mutex);

#if (APP_ENABLE_WAVEFORM_MAPPING != 0U) && \
    (APP_WAVEFORM_MAPPING_BACKEND_DAC != 0U)
    /* 同步窗口也包含 PA27，开始前同样避免 DAC 对 ADC 的干扰。 */
    (void)WaveformOutputDACStop();
#endif

    pa27_samples = FFTAnalysisAcquireADCCaptureBuffer(
        APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT);
    if (pa27_samples == NULL) {
        goto start_failed;
    }
    waveform_measurement_capture_samples[
        WAVEFORM_MEASUREMENT_INPUT_PA27] = pa27_samples;
    waveform_measurement_fft_workspace_reserved[
        WAVEFORM_MEASUREMENT_INPUT_PA27] = true;
    waveform_measurement_capture_samples[
        WAVEFORM_MEASUREMENT_INPUT_PA21] =
        waveform_measurement_synchronized_pa21_samples;
    waveform_measurement_fft_workspace_reserved[
        WAVEFORM_MEASUREMENT_INPUT_PA21] = false;

    pa27_capture_started = AnalogCaptureStartInput(
        ANALOG_CAPTURE_INPUT_PA27);
    pa21_capture_started = pa27_capture_started &&
        AnalogCaptureStartInput(ANALOG_CAPTURE_INPUT_PA21);
    if (!pa21_capture_started) {
        goto start_failed;
    }

    waveform_measurement_synchronized_request_active = true;
    if (ADCSamplingStartSynchronizedCapture(pa27_samples,
            FFT_ANALYSIS_ADC_CAPTURE_BUFFER_CAPACITY,
            waveform_measurement_synchronized_pa21_samples,
            APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT,
            APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT,
            APP_WAVEFORM_SYNCHRONIZED_SAMPLE_RATE_HZ,
            WaveformMeasurementADCSynchronizedCaptureCompleteFromISR,
            NULL)) {
        return true;
    }
    waveform_measurement_synchronized_request_active = false;

start_failed:
    if (pa21_capture_started) {
        (void)AnalogCaptureStopInput(ANALOG_CAPTURE_INPUT_PA21);
    }
    if (pa27_capture_started) {
        (void)AnalogCaptureStopInput(ANALOG_CAPTURE_INPUT_PA27);
    }
    WaveformMeasurementReleaseFFTWorkspace(
        WAVEFORM_MEASUREMENT_INPUT_PA27);
    waveform_measurement_capture_samples[
        WAVEFORM_MEASUREMENT_INPUT_PA21] = NULL;
    if (xSemaphoreTake(waveform_measurement_mutex,
            portMAX_DELAY) == pdPASS) {
        for (WaveformMeasurementInput_e input =
                 WAVEFORM_MEASUREMENT_INPUT_PA27;
             input < WAVEFORM_MEASUREMENT_INPUT_COUNT; ++input) {
            waveform_measurement_request_pending[input] = false;
            waveform_measurement_request_statuses[input] =
                WAVEFORM_MEASUREMENT_REQUEST_START_FAILED;
        }
        (void)xSemaphoreGive(waveform_measurement_mutex);
    }
    return false;
}
#endif

size_t WaveformMeasurementGetInputSampleCount(
    WaveformMeasurementInput_e input)
{
    if (!WaveformMeasurementInputIsValid(input)) {
        return 0U;
    }
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE != 0U
    return (size_t)APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT;
#else
    return (input == WAVEFORM_MEASUREMENT_INPUT_PA21)
               ? (size_t)APP_WAVEFORM_PA21_SAMPLE_COUNT
               : (size_t)APP_WAVEFORM_PA27_SAMPLE_COUNT;
#endif
}

uint32_t WaveformMeasurementGetInputSampleRateHz(
    WaveformMeasurementInput_e input)
{
    if (!WaveformMeasurementInputIsValid(input)) {
        return 0UL;
    }
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE != 0U
    return APP_WAVEFORM_SYNCHRONIZED_SAMPLE_RATE_HZ;
#else
    return (input == WAVEFORM_MEASUREMENT_INPUT_PA21)
               ? APP_WAVEFORM_PA21_SAMPLE_RATE_HZ
               : APP_WAVEFORM_PA27_SAMPLE_RATE_HZ;
#endif
}

uint32_t WaveformMeasurementGetInputFrequencyScaleNumerator(
    WaveformMeasurementInput_e input)
{
    if (!WaveformMeasurementInputIsValid(input)) {
        return 0UL;
    }
    return (input == WAVEFORM_MEASUREMENT_INPUT_PA21)
               ? APP_WAVEFORM_PA21_FREQUENCY_SCALE_NUMERATOR
               : APP_WAVEFORM_PA27_FREQUENCY_SCALE_NUMERATOR;
}

uint32_t WaveformMeasurementGetInputFrequencyScaleDenominator(
    WaveformMeasurementInput_e input)
{
    if (!WaveformMeasurementInputIsValid(input)) {
        return 0UL;
    }
    return (input == WAVEFORM_MEASUREMENT_INPUT_PA21)
               ? APP_WAVEFORM_PA21_FREQUENCY_SCALE_DENOMINATOR
               : APP_WAVEFORM_PA27_FREQUENCY_SCALE_DENOMINATOR;
}

bool WaveformMeasurementScaleInputFrequencyMillihz(
    WaveformMeasurementInput_e input,
    uint32_t measured_frequency_millihz,
    uint32_t *input_frequency_millihz)
{
    uint32_t scale_numerator =
        WaveformMeasurementGetInputFrequencyScaleNumerator(input);
    uint32_t scale_denominator =
        WaveformMeasurementGetInputFrequencyScaleDenominator(input);
    uint32_t calibration_numerator;
    uint32_t calibration_denominator;
    uint64_t calibrated_frequency;
    uint64_t scaled_frequency;

    if (!WaveformMeasurementInputIsValid(input) ||
        (input_frequency_millihz == NULL)) {
        return false;
    }
    calibration_numerator =
        (input == WAVEFORM_MEASUREMENT_INPUT_PA21)
            ? APP_WAVEFORM_PA21_FREQUENCY_CALIBRATION_NUMERATOR
            : APP_WAVEFORM_PA27_FREQUENCY_CALIBRATION_NUMERATOR;
    calibration_denominator =
        (input == WAVEFORM_MEASUREMENT_INPUT_PA21)
            ? APP_WAVEFORM_PA21_FREQUENCY_CALIBRATION_DENOMINATOR
            : APP_WAVEFORM_PA27_FREQUENCY_CALIBRATION_DENOMINATOR;
    if ((scale_numerator == 0UL) || (scale_denominator == 0UL) ||
        (calibration_numerator == 0UL) ||
        (calibration_denominator == 0UL)) {
        return false;
    }

    calibrated_frequency =
        (((uint64_t)measured_frequency_millihz *
             calibration_numerator) +
            (calibration_denominator / 2UL)) /
        calibration_denominator;
    if (calibrated_frequency > UINT32_MAX) {
        return false;
    }
    scaled_frequency =
        ((calibrated_frequency * scale_numerator) +
            (scale_denominator / 2UL)) /
        scale_denominator;
    if (scaled_frequency > UINT32_MAX) {
        return false;
    }
    *input_frequency_millihz = (uint32_t)scaled_frequency;
    return true;
}

bool WaveformMeasurementIsInputPending(
    WaveformMeasurementInput_e input)
{
    bool pending = false;

    if (!WaveformMeasurementInputIsValid(input) ||
        (waveform_measurement_mutex == NULL) ||
        (xSemaphoreTake(waveform_measurement_mutex,
             portMAX_DELAY) != pdPASS)) {
        return false;
    }
    pending = waveform_measurement_request_pending[input];
    (void)xSemaphoreGive(waveform_measurement_mutex);
    return pending;
}

WaveformMeasurementRequestStatus_e WaveformMeasurementGetRequestStatus(
    WaveformMeasurementInput_e input)
{
    WaveformMeasurementRequestStatus_e status =
        WAVEFORM_MEASUREMENT_REQUEST_IDLE;

    if (!WaveformMeasurementInputIsValid(input) ||
        (waveform_measurement_mutex == NULL) ||
        (xSemaphoreTake(waveform_measurement_mutex,
             portMAX_DELAY) != pdPASS)) {
        return status;
    }
    status = waveform_measurement_request_statuses[input];
    (void)xSemaphoreGive(waveform_measurement_mutex);
    return status;
}

bool WaveformMeasurementSetInput(
    WaveformMeasurementInput_e input)
{
    if (!WaveformMeasurementInputIsValid(input) ||
        !WaveformMeasurementIsInputEnabled(input) ||
        (waveform_measurement_mutex == NULL) ||
        (xSemaphoreTake(waveform_measurement_mutex,
             portMAX_DELAY) != pdPASS)) {
        return false;
    }

    waveform_measurement_input = input;
    (void)xSemaphoreGive(waveform_measurement_mutex);
    return true;
}

WaveformMeasurementInput_e WaveformMeasurementGetInput(void)
{
    WaveformMeasurementInput_e input =
        WAVEFORM_MEASUREMENT_INPUT_COUNT;

    if ((waveform_measurement_mutex != NULL) &&
        (xSemaphoreTake(waveform_measurement_mutex,
             portMAX_DELAY) == pdPASS)) {
        input = waveform_measurement_input;
        (void)xSemaphoreGive(waveform_measurement_mutex);
    }
    return input;
}

bool WaveformMeasurementCopyLatest(
    WaveformMeasurement *measurement)
{
    WaveformMeasurementInput_e input;

    if ((measurement == NULL) ||
        (waveform_measurement_mutex == NULL) ||
        (xSemaphoreTake(waveform_measurement_mutex,
             portMAX_DELAY) != pdPASS)) {
        return false;
    }

    input = waveform_measurement_input;
    if (!WaveformMeasurementIsInputEnabled(input)) {
        (void)xSemaphoreGive(waveform_measurement_mutex);
        return false;
    }
    if (!waveform_measurement_result_ready[input]) {
        (void)xSemaphoreGive(waveform_measurement_mutex);
        return false;
    }
    *measurement = waveform_measurement_results[input];
    (void)xSemaphoreGive(waveform_measurement_mutex);
    return true;
}

bool WaveformMeasurementCopyLatestInput(
    WaveformMeasurementInput_e input,
    WaveformMeasurement *measurement)
{
    if (!WaveformMeasurementInputIsValid(input) ||
        !WaveformMeasurementIsInputEnabled(input) ||
        (measurement == NULL) ||
        (waveform_measurement_mutex == NULL) ||
        (xSemaphoreTake(waveform_measurement_mutex,
             portMAX_DELAY) != pdPASS)) {
        return false;
    }

    if (!waveform_measurement_result_ready[input]) {
        (void)xSemaphoreGive(waveform_measurement_mutex);
        return false;
    }

    *measurement = waveform_measurement_results[input];
    (void)xSemaphoreGive(waveform_measurement_mutex);
    return true;
}

/* 分块复制已发布结果最后 128 点，页面和 UART2 无需保留完整原始窗口。 */
bool WaveformMeasurementCopyLatestInputSamples(
    WaveformMeasurementInput_e input, uint32_t result_sequence,
    size_t offset, uint16_t *samples, size_t capacity,
    size_t *copied_count)
{
    const uint16_t *source;
    size_t retained_start;
    size_t available_count;
    size_t copy_count;
    size_t index;

    if (!WaveformMeasurementInputIsValid(input) ||
        !WaveformMeasurementIsInputEnabled(input) ||
        (samples == NULL) || (capacity == 0U) ||
        (copied_count == NULL) ||
        (waveform_measurement_mutex == NULL) ||
        (xSemaphoreTake(waveform_measurement_mutex,
             portMAX_DELAY) != pdPASS)) {
        return false;
    }

    if (!waveform_measurement_result_ready[input] ||
        waveform_measurement_request_pending[input] ||
        (waveform_measurement_results[input].sequence !=
            result_sequence) ||
        (offset >= waveform_measurement_results[input].sample_count)) {
        (void)xSemaphoreGive(waveform_measurement_mutex);
        return false;
    }
    retained_start =
        (waveform_measurement_results[input].sample_count >
            WAVEFORM_MEASUREMENT_RETAINED_SAMPLE_COUNT)
            ? waveform_measurement_results[input].sample_count -
                  WAVEFORM_MEASUREMENT_RETAINED_SAMPLE_COUNT
            : 0U;
    if (offset < retained_start) {
        (void)xSemaphoreGive(waveform_measurement_mutex);
        return false;
    }
    source = WaveformMeasurementGetRetainedSampleBuffer(input);
    if (source == NULL) {
        (void)xSemaphoreGive(waveform_measurement_mutex);
        return false;
    }

    available_count =
        waveform_measurement_results[input].sample_count - offset;
    copy_count = (available_count < capacity)
                     ? available_count
                     : capacity;
    for (index = 0U; index < copy_count; ++index) {
        samples[index] = source[(offset - retained_start) + index];
    }
    *copied_count = copy_count;
    (void)xSemaphoreGive(waveform_measurement_mutex);
    return true;
}

bool WaveformMeasurementSubscribeResultReady(
    WaveformMeasurementResultReadyCallback_t callback,
    void *context)
{
    size_t index;
    size_t free_index = WAVEFORM_MEASUREMENT_RESULT_SUBSCRIBER_COUNT;

    if ((callback == NULL) || (waveform_measurement_mutex == NULL) ||
        (xSemaphoreTake(waveform_measurement_mutex,
             portMAX_DELAY) != pdPASS)) {
        return false;
    }

    for (index = 0U;
         index < WAVEFORM_MEASUREMENT_RESULT_SUBSCRIBER_COUNT;
         ++index) {
        WaveformMeasurementResultSubscriber *subscriber =
            &waveform_measurement_result_subscribers[index];

        if ((subscriber->callback == callback) &&
            (subscriber->context == context)) {
            (void)xSemaphoreGive(waveform_measurement_mutex);
            return true;
        }
        if ((subscriber->callback == NULL) &&
            (free_index == WAVEFORM_MEASUREMENT_RESULT_SUBSCRIBER_COUNT)) {
            free_index = index;
        }
    }

    if (free_index < WAVEFORM_MEASUREMENT_RESULT_SUBSCRIBER_COUNT) {
        waveform_measurement_result_subscribers[free_index].callback =
            callback;
        waveform_measurement_result_subscribers[free_index].context =
            context;
    }
    (void)xSemaphoreGive(waveform_measurement_mutex);
    return free_index < WAVEFORM_MEASUREMENT_RESULT_SUBSCRIBER_COUNT;
}

bool WaveformMeasurementUnsubscribeResultReady(
    WaveformMeasurementResultReadyCallback_t callback,
    void *context)
{
    size_t index;

    if ((callback == NULL) || (waveform_measurement_mutex == NULL) ||
        (xSemaphoreTake(waveform_measurement_mutex,
             portMAX_DELAY) != pdPASS)) {
        return false;
    }

    for (index = 0U;
         index < WAVEFORM_MEASUREMENT_RESULT_SUBSCRIBER_COUNT;
         ++index) {
        WaveformMeasurementResultSubscriber *subscriber =
            &waveform_measurement_result_subscribers[index];

        if ((subscriber->callback == callback) &&
            (subscriber->context == context)) {
            subscriber->callback = NULL;
            subscriber->context  = NULL;
            (void)xSemaphoreGive(waveform_measurement_mutex);
            return true;
        }
    }

    (void)xSemaphoreGive(waveform_measurement_mutex);
    return false;
}

bool WaveformMeasurementIsRunning(void)
{
    WaveformMeasurementInput_e input;

    if (!waveform_measurement_task_created ||
        !FFTAnalysisIsRunning()) {
        return false;
    }
    for (input = WAVEFORM_MEASUREMENT_INPUT_PA27;
         input < WAVEFORM_MEASUREMENT_INPUT_COUNT;
         input = (WaveformMeasurementInput_e)((uint32_t)input + 1UL)) {
        if (WaveformMeasurementIsInputPending(input)) {
            return true;
        }
    }
    return false;
}

bool WaveformMeasurementAnalyzeExternalSamples(
    WaveformMeasurementInput_e input, const uint16_t *samples,
    size_t sample_count, uint32_t sample_rate_hz,
    uint32_t source_sequence)
{
    WaveformMeasurementTimeFeatures time_features;
    FFTAnalysisResult fft_result;
    WaveformMeasurement measurement;
    uint16_t short_fft_samples[FFT_ANALYSIS_UART2_POINT_COUNT];
    const uint16_t *fft_samples = samples;
    size_t fft_sample_count = FFT_ANALYSIS_UART2_POINT_COUNT;
    size_t index;

    if (!WaveformMeasurementInputIsValid(input) ||
        !WaveformMeasurementIsInputEnabled(input) ||
        (samples == NULL) || (sample_count < 2U) ||
        (sample_count > FFT_ANALYSIS_MAX_POINT_COUNT) ||
        (sample_rate_hz == 0UL) ||
        !waveform_measurement_task_created ||
        !FFTAnalysisIsRunning()) {
        return false;
    }

    /* 选择不超过原始窗口的最大支持 FFT 点数，避免填充数据改变波形。 */
    while ((fft_sample_count * 2U <= sample_count) &&
           (fft_sample_count < FFT_ANALYSIS_MAX_POINT_COUNT)) {
        fft_sample_count *= 2U;
    }
    if (sample_count < fft_sample_count) {
        /* FFT 最少需要 64 点；短窗口只补齐频谱输入，不改变时域统计。 */
        for (index = 0U; index < fft_sample_count; ++index) {
            short_fft_samples[index] =
                (index < sample_count) ? samples[index]
                                       : samples[sample_count - 1U];
        }
        fft_samples = short_fft_samples;
    }
    if (!WaveformMeasurementExtractTimeFeatures(
            samples, sample_count, &time_features) ||
        !FFTAnalysisAnalyzeADCSamples(
            WaveformMeasurementMapFFTInput(input), fft_samples,
            fft_sample_count, sample_rate_hz, source_sequence) ||
        !FFTAnalysisCopyLatestResult(
            WaveformMeasurementMapFFTInput(input), &fft_result) ||
        (fft_result.source_sequence != source_sequence) ||
        !WaveformMeasurementCalculate(input, &time_features, sample_count,
            sample_rate_hz, &fft_result, NULL, &measurement)) {
        return false;
    }

    /* 保留最新窗口末尾样本，使现有结果读取接口也能查看阈值采样数据。 */
    WaveformMeasurementRetainSamples(input, samples, sample_count);
    WaveformMeasurementCommitRetainedSamples(input, sample_count);
    WaveformMeasurementPublish(&measurement, input);
    return true;
}

static void WaveformMeasurementTask(void *argument)
{
    /*
     * Capture 频率/占空比结果可能早于 ADC 采样完成，因此按输入缓存最近一次
     * 结果、序列号和更新时间，待 ADC 数据齐全时再判断是否可用。
     */
    AnalogCaptureMeasurement latest_capture_results[
        WAVEFORM_MEASUREMENT_INPUT_COUNT];
    uint32_t latest_capture_sequences[
        WAVEFORM_MEASUREMENT_INPUT_COUNT] = {
            UINT32_MAX, UINT32_MAX
        };
    TickType_t latest_capture_update_times[
        WAVEFORM_MEASUREMENT_INPUT_COUNT] = {0U, 0U};
    bool capture_results_ready[
        WAVEFORM_MEASUREMENT_INPUT_COUNT] = {false, false};

    (void)argument;

    /* 一次唤醒可能同时对应多路输入，下面按输入编号逐路完成测量。 */
    for (;;) {
        WaveformMeasurementInput_e input;
        TickType_t current_time;

        /* 任务在 ApplicationInit() 阶段创建，调度器未运行时不访问 RTOS 服务。 */
        if (xTaskGetSchedulerState() != taskSCHEDULER_RUNNING) {
            vTaskDelay(1U);
            continue;
        }
        /*
         * ADC 块完成和 Capture 更新会唤醒任务；100 ms 超时用于推进请求超时
         * 检查，防止输入停止后任务永久等待。
         */
        (void)ulTaskNotifyTake(pdTRUE,
            pdMS_TO_TICKS(WAVEFORM_MEASUREMENT_WAIT_TIMEOUT_MS));
        current_time = xTaskGetTickCount();

        /* 只处理已启用且存在请求的输入，未请求的输入不触碰共享资源。 */
        /* PA27 和 PA21 共用同一任务，逐路处理各自独立的请求状态。 */
        for (input = WAVEFORM_MEASUREMENT_INPUT_PA27;
             input < WAVEFORM_MEASUREMENT_INPUT_COUNT; ++input) {
            uint32_t source_sequence;
            uint16_t *measurement_samples;
            FFTAnalysisResult fft_result;
            WaveformMeasurement measurement;
            WaveformMeasurementTimeFeatures time_features;
            AnalogCaptureMeasurement capture_result;
            const AnalogCaptureMeasurement *capture_result_to_use = NULL;
            AnalogCaptureInput_e capture_input =
                WaveformMeasurementMapCaptureInput(input);

            /* 编译配置关闭的输入不占用本轮处理时间。 */
            if (!WaveformMeasurementIsInputEnabled(input)) {
                continue;
            }
            /* 没有测量请求时丢弃旧 Capture 缓存，避免下次请求误用。 */
            if (!WaveformMeasurementIsInputPending(input)) {
                capture_results_ready[input] = false;
                latest_capture_sequences[input] = UINT32_MAX;
                continue;
            }
            /* 请求期间指向已经由本输入独占的共享 ADC/FFT 工作区。 */
            measurement_samples =
                WaveformMeasurementGetSampleBuffer(input);
            if (measurement_samples == NULL) {
                waveform_measurement_request_statuses[input] =
                    WAVEFORM_MEASUREMENT_REQUEST_START_FAILED;
                WaveformMeasurementCompleteRequest(input);
                capture_results_ready[input] = false;
                latest_capture_sequences[input] = UINT32_MAX;
                continue;
            }
            /* 收满的数据优先进入计算，不能因任务调度稍晚而误判超时。 */
            if ((waveform_measurement_collected_sample_counts[input] <
                    WaveformMeasurementGetInputSampleCount(input)) &&
                WaveformMeasurementRequestHasTimedOut(
                    input, current_time)) {
                waveform_measurement_request_statuses[input] =
                    WAVEFORM_MEASUREMENT_REQUEST_TIMEOUT;
                WaveformMeasurementCompleteRequest(input);
                capture_results_ready[input] = false;
                latest_capture_sequences[input] = UINT32_MAX;
                continue;
            }

            /* 刷新比较器 Capture 的频率和占空比结果缓存。 */
            if (!AnalogCaptureIsInputRunning(capture_input)) {
                capture_results_ready[input] = false;
                latest_capture_sequences[input] = UINT32_MAX;
            } else if (AnalogCaptureReadInputMeasurement(
                           capture_input, &capture_result) &&
                       (!capture_results_ready[input] ||
                           (capture_result.sequence !=
                               latest_capture_sequences[input]))) {
                latest_capture_results[input] = capture_result;
                latest_capture_sequences[input] =
                    capture_result.sequence;
                latest_capture_update_times[input] = current_time;
                capture_results_ready[input] = true;
            }

            /* 只有属于当前时间窗口的 Capture 结果才能参与最终计算。 */
            if (capture_results_ready[input] &&
                WaveformMeasurementCaptureIsFresh(
                    &latest_capture_results[input],
                    latest_capture_update_times[input], current_time)) {
                capture_result_to_use = &latest_capture_results[input];
            }

            /* ADC 点数收齐后依次执行 FFT、参数计算、发布和资源释放。 */
            if (waveform_measurement_collected_sample_counts[input] >=
                WaveformMeasurementGetInputSampleCount(input)) {
                bool fft_analyzed;

                source_sequence =
                    waveform_measurement_request_source_sequences[input];
                /*
                 * FFT 会把 DMA 原始样本原地展开为复数，因此先保存分类所需
                 * 的时域统计量，以及页面和 UART2 使用的最后 128 点。
                 */
                if (!WaveformMeasurementExtractTimeFeatures(
                        measurement_samples,
                        waveform_measurement_collected_sample_counts[input],
                        &time_features)) {
                    waveform_measurement_request_statuses[input] =
                        WAVEFORM_MEASUREMENT_REQUEST_CALCULATION_FAILED;
                    WaveformMeasurementCompleteRequest(input);
                    capture_results_ready[input] = false;
                    latest_capture_sequences[input] = UINT32_MAX;
                    continue;
                }
                WaveformMeasurementRetainSamples(input,
                    measurement_samples,
                    waveform_measurement_collected_sample_counts[input]);
                /*
                 * FFT 结果必须与本次 ADC 序列和点数完全一致，防止使用上一轮
                 * 测量留下的结果。
                 */
                if (waveform_measurement_fft_workspace_reserved[input]) {
                    fft_analyzed = FFTAnalysisAnalyzeCapturedADCSamples(
                            WaveformMeasurementMapFFTInput(input),
                            waveform_measurement_collected_sample_counts[
                                input],
                            WaveformMeasurementGetInputSampleRateHz(input),
                            source_sequence);
                } else {
                    /* 同步采集的 PA21 使用独立 DMA 缓冲区，顺序分析即可。 */
                    fft_analyzed = FFTAnalysisAnalyzeADCSamples(
                            WaveformMeasurementMapFFTInput(input),
                            measurement_samples,
                            waveform_measurement_collected_sample_counts[
                                input],
                            WaveformMeasurementGetInputSampleRateHz(input),
                            source_sequence);
                }
                /* 分析接口无论成功与否都已经归还共享工作区。 */
                waveform_measurement_fft_workspace_reserved[input] = false;
                waveform_measurement_capture_samples[input] = NULL;
                if (!fft_analyzed ||
                    !FFTAnalysisCopyLatestResult(
                        WaveformMeasurementMapFFTInput(input),
                        &fft_result) ||
                    (fft_result.source_sequence != source_sequence) ||
                    (fft_result.point_count !=
                        waveform_measurement_collected_sample_counts[input])) {
                    waveform_measurement_request_statuses[input] =
                        WAVEFORM_MEASUREMENT_REQUEST_FFT_FAILED;
                    WaveformMeasurementCompleteRequest(input);
                    capture_results_ready[input] = false;
                    latest_capture_sequences[input] = UINT32_MAX;
                    continue;
                }
                WaveformMeasurementUpdatePhaseFFTFrame(
                    input, &fft_result);
                /* 融合 ADC、FFT 和可用的 Capture 数据得到统一测量结果。 */
                if (!WaveformMeasurementCalculate(input,
                    &time_features,
                    waveform_measurement_collected_sample_counts[input],
                    WaveformMeasurementGetInputSampleRateHz(input),
                    &fft_result,
                    capture_result_to_use,
                    &measurement)) {
                    waveform_measurement_request_statuses[input] =
                        WAVEFORM_MEASUREMENT_REQUEST_CALCULATION_FAILED;
                    WaveformMeasurementCompleteRequest(input);
                    capture_results_ready[input] = false;
                    latest_capture_sequences[input] = UINT32_MAX;
                    continue;
                }
                WaveformMeasurementCommitRetainedSamples(input,
                    waveform_measurement_collected_sample_counts[input]);
                /* 先关闭 ADC/Capture，再发布结果供显示和 UART2 统一读取。 */
                waveform_measurement_request_statuses[input] =
                    WAVEFORM_MEASUREMENT_REQUEST_COMPLETE;
                WaveformMeasurementCompleteRequest(input);
                WaveformMeasurementPublish(&measurement, input);
                WaveformMeasurementTryPublishSynchronizedPhase(
                    source_sequence);
                capture_results_ready[input] = false;
                latest_capture_sequences[input] = UINT32_MAX;
            }
        }

    }
}

/* 保存同步相位所需的主峰复数向量，避免长期保留两份完整 FFT。 */
static void WaveformMeasurementUpdatePhaseFFTFrame(
    WaveformMeasurementInput_e input,
    const FFTAnalysisResult *fft_result)
{
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
    WaveformMeasurementPhaseFFTFrame *frame;

    if (!WaveformMeasurementInputIsValid(input) ||
        (fft_result == NULL)) {
        return;
    }
    frame = &waveform_measurement_phase_fft_frames[input];
    frame->peak_real = fft_result->peak_real;
    frame->peak_imaginary = fft_result->peak_imaginary;
    frame->peak_magnitude = fft_result->peak_magnitude;
    frame->peak_bin = fft_result->peak_bin;
    frame->point_count = fft_result->point_count;
    frame->peak_frequency_millihz =
        fft_result->peak_frequency_millihz;
    frame->sample_rate_hz = fft_result->sample_rate_hz;
    frame->source_sequence = fft_result->source_sequence;
    frame->ready = true;
#else
    (void)input;
    (void)fft_result;
#endif
}

/* 同一采集序列的两路 FFT 都完成后，计算 PB19 相对 PA27 的相位差。 */
static void WaveformMeasurementTryPublishSynchronizedPhase(
    uint32_t source_sequence)
{
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
    const WaveformMeasurementPhaseFFTFrame *pa27 =
        &waveform_measurement_phase_fft_frames[
            WAVEFORM_MEASUREMENT_INPUT_PA27];
    const WaveformMeasurementPhaseFFTFrame *pb19 =
        &waveform_measurement_phase_fft_frames[
            WAVEFORM_MEASUREMENT_INPUT_PB19];
    WaveformSynchronizedPhaseMeasurement result = {0};
    uint64_t frequency_difference_millihz;

    if (!pa27->ready || !pb19->ready ||
        (pa27->source_sequence != source_sequence) ||
        (pb19->source_sequence != source_sequence)) {
        return;
    }

    result.source_sequence = source_sequence;
    result.sample_rate_hz = pa27->sample_rate_hz;
    result.sample_count = pa27->point_count;
    result.pa27_peak_magnitude = pa27->peak_magnitude;
    result.pb19_peak_magnitude = pb19->peak_magnitude;
    result.frequency_millihz = (uint32_t)(
        (((uint64_t)pa27->peak_frequency_millihz +
             pb19->peak_frequency_millihz) + 1ULL) /
        2ULL);
    result.timestamp_ticks = (uint32_t)xTaskGetTickCount();
    frequency_difference_millihz =
        (pa27->peak_frequency_millihz >=
             pb19->peak_frequency_millihz)
            ? ((uint64_t)pa27->peak_frequency_millihz -
                pb19->peak_frequency_millihz)
            : ((uint64_t)pb19->peak_frequency_millihz -
                pa27->peak_frequency_millihz);

    if ((pa27->peak_magnitude <
                    WAVEFORM_MEASUREMENT_PHASE_MINIMUM_PEAK_MAGNITUDE) ||
               (pb19->peak_magnitude <
                    WAVEFORM_MEASUREMENT_PHASE_MINIMUM_PEAK_MAGNITUDE)) {
        result.status = WAVEFORM_SYNCHRONIZED_PHASE_STATUS_NO_SIGNAL;
    } else if ((pa27->sample_rate_hz != pb19->sample_rate_hz) ||
               (pa27->point_count != pb19->point_count) ||
               (pa27->peak_bin != pb19->peak_bin) ||
               (frequency_difference_millihz >
                   (((uint64_t)pa27->sample_rate_hz * 1000ULL *
                       WAVEFORM_MEASUREMENT_PHASE_FREQUENCY_TOLERANCE_BINS) /
                       pa27->point_count))) {
        result.status =
            WAVEFORM_SYNCHRONIZED_PHASE_STATUS_FREQUENCY_MISMATCH;
    } else {
        int64_t relative_real =
            ((int64_t)pb19->peak_real * pa27->peak_real) +
            ((int64_t)pb19->peak_imaginary *
                pa27->peak_imaginary);
        int64_t relative_imaginary =
            ((int64_t)pb19->peak_imaginary * pa27->peak_real) -
            ((int64_t)pb19->peak_real * pa27->peak_imaginary);
        q31_t angle_q29 = 0;

        result.common_peak_bin = pa27->peak_bin;
        if (((relative_real == 0LL) &&
                (relative_imaginary == 0LL)) ||
            (arm_atan2_q31(
                 (q31_t)WaveformMeasurementSaturateQ31(
                     relative_imaginary),
                 (q31_t)WaveformMeasurementSaturateQ31(relative_real),
                 &angle_q29) != ARM_MATH_SUCCESS)) {
            result.status =
                WAVEFORM_SYNCHRONIZED_PHASE_STATUS_CALCULATION_FAILED;
        } else {
            int32_t phase_millidegrees = (int32_t)(
                ((int64_t)angle_q29 * 180000LL) /
                WAVEFORM_MEASUREMENT_PI_Q29);

            phase_millidegrees +=
                APP_WAVEFORM_SYNCHRONIZED_PHASE_OFFSET_MILLIDEGREES;
            result.phase_millidegrees =
                WaveformMeasurementWrapPhaseMillidegrees(
                    phase_millidegrees);
            result.status = WAVEFORM_SYNCHRONIZED_PHASE_STATUS_VALID;
        }
    }

    if ((waveform_measurement_mutex != NULL) &&
        (xSemaphoreTake(waveform_measurement_mutex,
             portMAX_DELAY) == pdPASS)) {
        result.sequence =
            ++waveform_measurement_synchronized_phase_sequence;
        waveform_measurement_synchronized_phase_result = result;
        (void)xSemaphoreGive(waveform_measurement_mutex);
    }
#else
    (void)source_sequence;
#endif
}

#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
/* 交给 CMSIS-DSP 前钳位乘积，防止缩窄为 q31_t 时发生回绕。 */
static int32_t WaveformMeasurementSaturateQ31(int64_t value)
{
    if (value > INT32_MAX) {
        return INT32_MAX;
    }
    if (value < INT32_MIN) {
        return INT32_MIN;
    }
    return (int32_t)value;
}

/* 将校准后的相位差归一化到闭区间 -180°～180°。 */
static int32_t WaveformMeasurementWrapPhaseMillidegrees(
    int32_t phase_millidegrees)
{
    if (phase_millidegrees > 180000) {
        phase_millidegrees -= 360000;
    } else if (phase_millidegrees < -180000) {
        phase_millidegrees += 360000;
    }
    return phase_millidegrees;
}
#endif

/* 发布一次结果后释放本请求持有的 ADC 引用，并停止对应 Capture。 */
static void WaveformMeasurementCompleteRequest(
    WaveformMeasurementInput_e input)
{
    AnalogCaptureInput_e capture_input =
        WaveformMeasurementMapCaptureInput(input);

#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE != 0U
    if (waveform_measurement_synchronized_request_active) {
        bool finish_synchronized_capture = false;

        (void)AnalogCaptureStopInput(capture_input);
        WaveformMeasurementReleaseFFTWorkspace(input);
        if ((waveform_measurement_mutex != NULL) &&
            (xSemaphoreTake(waveform_measurement_mutex,
                 portMAX_DELAY) == pdPASS)) {
            waveform_measurement_request_pending[input] = false;
            finish_synchronized_capture =
                !waveform_measurement_request_pending[
                    WAVEFORM_MEASUREMENT_INPUT_PA27] &&
                !waveform_measurement_request_pending[
                    WAVEFORM_MEASUREMENT_INPUT_PA21];
            (void)xSemaphoreGive(waveform_measurement_mutex);
        }
        if (finish_synchronized_capture) {
            (void)ADCSamplingFinishSynchronizedCapture();
            waveform_measurement_synchronized_request_active = false;
        }
        return;
    }
#endif

    (void)ADCSamplingFinishDirectInputCapture(
        WaveformMeasurementMapADCInput(input));
    (void)AnalogCaptureStopInput(capture_input);
    WaveformMeasurementReleaseFFTWorkspace(input);
    if ((waveform_measurement_mutex != NULL) &&
        (xSemaphoreTake(waveform_measurement_mutex,
             portMAX_DELAY) == pdPASS)) {
        waveform_measurement_request_pending[input] = false;
        (void)xSemaphoreGive(waveform_measurement_mutex);
    }
}

/*
 * 两路输入都由 DMA 直接填满最终 N 点缓冲区；这里只提交元数据并唤醒任务，
 * 不再拼接 64 点块，也不会在块间产生软件重装空档。
 */
static void WaveformMeasurementADCDirectCaptureCompleteFromISR(
    ADCSamplingInput_e input, uint32_t source_sequence,
    void *context)
{
    BaseType_t higher_priority_task_woken = pdFALSE;
    WaveformMeasurementInput_e measurement_input;

    (void)context;
    measurement_input =
        (input == ADC_SAMPLING_INPUT_PA21)
            ? WAVEFORM_MEASUREMENT_INPUT_PA21
            : WAVEFORM_MEASUREMENT_INPUT_PA27;
    if (!WaveformMeasurementInputIsValid(measurement_input) ||
        !waveform_measurement_request_pending[measurement_input]) {
        return;
    }

    waveform_measurement_request_source_sequences[measurement_input] =
        source_sequence;
    waveform_measurement_collected_sample_counts[measurement_input] =
        WaveformMeasurementGetInputSampleCount(measurement_input);
    waveform_measurement_last_progress_ticks[measurement_input] =
        (uint32_t)xTaskGetTickCountFromISR();
    waveform_measurement_accepted_block_counts[measurement_input] = 1UL;
    if (waveform_measurement_task_handle != NULL) {
        vTaskNotifyGiveFromISR(waveform_measurement_task_handle,
            &higher_priority_task_woken);
        portYIELD_FROM_ISR(higher_priority_task_woken);
    }
}

#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE != 0U
/* 两路 DMA 都完成后一次性发布相同的采集序列，保证窗口严格配对。 */
static void WaveformMeasurementADCSynchronizedCaptureCompleteFromISR(
    uint32_t source_sequence, void *context)
{
    BaseType_t higher_priority_task_woken = pdFALSE;
    WaveformMeasurementInput_e input;

    (void)context;
    if (!waveform_measurement_synchronized_request_active) {
        return;
    }

    for (input = WAVEFORM_MEASUREMENT_INPUT_PA27;
         input < WAVEFORM_MEASUREMENT_INPUT_COUNT; ++input) {
        if (!waveform_measurement_request_pending[input]) {
            continue;
        }
        waveform_measurement_request_source_sequences[input] =
            source_sequence;
        waveform_measurement_collected_sample_counts[input] =
            APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT;
        waveform_measurement_last_progress_ticks[input] =
            (uint32_t)xTaskGetTickCountFromISR();
        waveform_measurement_accepted_block_counts[input] = 1UL;
    }
    if (waveform_measurement_task_handle != NULL) {
        vTaskNotifyGiveFromISR(waveform_measurement_task_handle,
            &higher_priority_task_woken);
        portYIELD_FROM_ISR(higher_priority_task_woken);
    }
}
#endif

#if APP_ENABLE_UART2 != 0U
/* UART2 接收回调只把样本交给 FFT 外部输入，不在串口任务中执行分析。 */
static void WaveformMeasurementUART2SampleReceived(
    int16_t sample, void *context)
{
    (void)context;
    (void)FFTAnalysisSubmitUART2Sample(sample);
}
#endif

static bool WaveformMeasurementInputIsValid(
    WaveformMeasurementInput_e input)
{
    return (input >= WAVEFORM_MEASUREMENT_INPUT_PA27) &&
           (input < WAVEFORM_MEASUREMENT_INPUT_COUNT);
}

/* 两路都用 TIMG0 精确产生配置采样率，并由一次 DMA 收满完整窗口。 */
static bool WaveformMeasurementInputConfigIsValid(
    WaveformMeasurementInput_e input)
{
    uint32_t sample_rate_hz =
        WaveformMeasurementGetInputSampleRateHz(input);
    size_t sample_count =
        WaveformMeasurementGetInputSampleCount(input);

    if (!WaveformMeasurementInputIsValid(input) ||
        (sample_count < 64U) ||
        (sample_count > FFT_ANALYSIS_MAX_POINT_COUNT) ||
        ((sample_count & (sample_count - 1U)) != 0U) ||
        (sample_rate_hz == 0UL)) {
        return false;
    }
    return ADCSamplingIsSampleRateSupported(sample_rate_hz);
}

/* 按理论采集时长乘安全系数并叠加固定余量，得到整次请求截止时间。 */
static TickType_t WaveformMeasurementGetRequestTimeoutTicks(
    WaveformMeasurementInput_e input)
{
    uint64_t duration_milliseconds;
    uint32_t sample_rate_hz =
        WaveformMeasurementGetInputSampleRateHz(input);
    size_t sample_count =
        WaveformMeasurementGetInputSampleCount(input);

    if ((sample_rate_hz == 0UL) || (sample_count == 0U)) {
        return pdMS_TO_TICKS(
            WAVEFORM_MEASUREMENT_REQUEST_TIMEOUT_MARGIN_MS);
    }
    duration_milliseconds =
        (((uint64_t)sample_count * 1000ULL) +
            sample_rate_hz - 1ULL) /
        sample_rate_hz;
    duration_milliseconds =
        (duration_milliseconds *
            WAVEFORM_MEASUREMENT_REQUEST_MAXIMUM_MULTIPLIER) +
        WAVEFORM_MEASUREMENT_REQUEST_TIMEOUT_MARGIN_MS;
    if (duration_milliseconds > UINT32_MAX) {
        duration_milliseconds = UINT32_MAX;
    }
    return pdMS_TO_TICKS((uint32_t)duration_milliseconds);
}

/*
 * 一次 DMA 在 1.5 s 内没有完成即认为链路停滞；同时保留按理论采样时长
 * 计算的总超时，覆盖低采样率配置。
 */
static bool WaveformMeasurementRequestHasTimedOut(
    WaveformMeasurementInput_e input, TickType_t current_time)
{
    TickType_t last_progress_time;
    TickType_t total_elapsed;
    TickType_t stalled_time;

    if (!WaveformMeasurementInputIsValid(input)) {
        return true;
    }
    last_progress_time =
        (TickType_t)waveform_measurement_last_progress_ticks[input];
    total_elapsed = (TickType_t)(current_time -
        waveform_measurement_request_start_ticks[input]);
    stalled_time = (TickType_t)(current_time - last_progress_time);

    return (stalled_time > pdMS_TO_TICKS(
                WAVEFORM_MEASUREMENT_REQUEST_STALL_TIMEOUT_MS)) ||
           (total_elapsed >
                WaveformMeasurementGetRequestTimeoutTicks(input));
}

static uint16_t *WaveformMeasurementGetSampleBuffer(
    WaveformMeasurementInput_e input)
{
    return WaveformMeasurementInputIsValid(input)
               ? waveform_measurement_capture_samples[input]
               : NULL;
}

static uint16_t *WaveformMeasurementGetRetainedSampleBuffer(
    WaveformMeasurementInput_e input)
{
#if APP_ENABLE_WAVEFORM_PA27 != 0U
    if (input == WAVEFORM_MEASUREMENT_INPUT_PA27) {
        return waveform_measurement_pa27_retained_samples;
    }
#endif
#if APP_ENABLE_WAVEFORM_PA21 != 0U
    if (input == WAVEFORM_MEASUREMENT_INPUT_PA21) {
        return waveform_measurement_pa21_retained_samples;
    }
#endif
    return NULL;
}

/* FFT 原地覆盖样本前一次性提取分类与幅值计算需要的全部时域特征。 */
static bool WaveformMeasurementExtractTimeFeatures(
    const uint16_t *samples, size_t sample_count,
    WaveformMeasurementTimeFeatures *features)
{
    uint32_t sum_raw = 0UL;
    uint32_t peak_to_peak_raw;
    uint32_t lower_rail_limit;
    uint32_t upper_rail_limit;
    uint16_t threshold_raw;
    int32_t previous_step = 0;
    bool previous_step_valid = false;
    size_t index;

    if ((samples == NULL) || (sample_count < 2U) ||
        (features == NULL)) {
        return false;
    }
    *features = (WaveformMeasurementTimeFeatures){0};
    features->minimum_raw = samples[0];
    features->maximum_raw = samples[0];
    for (index = 0U; index < sample_count; ++index) {
        uint16_t sample = samples[index];

        if (sample < features->minimum_raw) {
            features->minimum_raw = sample;
        }
        if (sample > features->maximum_raw) {
            features->maximum_raw = sample;
        }
        sum_raw += sample;
    }
    features->average_raw = (uint16_t)(
        (sum_raw + (sample_count / 2U)) / sample_count);
    peak_to_peak_raw =
        features->maximum_raw - features->minimum_raw;
    threshold_raw = (uint16_t)(features->minimum_raw +
        (peak_to_peak_raw / 2U));
    lower_rail_limit = features->minimum_raw + (uint32_t)(
        ((uint64_t)peak_to_peak_raw *
            WAVEFORM_MEASUREMENT_CLASSIFY_RAIL_MARGIN) /
        WAVEFORM_MEASUREMENT_CLASSIFY_SCALE);
    upper_rail_limit = features->maximum_raw - (uint32_t)(
        ((uint64_t)peak_to_peak_raw *
            WAVEFORM_MEASUREMENT_CLASSIFY_RAIL_MARGIN) /
        WAVEFORM_MEASUREMENT_CLASSIFY_SCALE);

    for (index = 0U; index < sample_count; ++index) {
        int32_t centered =
            (int32_t)samples[index] - (int32_t)features->average_raw;
        uint32_t absolute_centered = (centered < 0)
            ? (uint32_t)(-centered)
            : (uint32_t)centered;

        if ((peak_to_peak_raw >=
                WAVEFORM_MEASUREMENT_MINIMUM_P2P_RAW) &&
            (samples[index] >= threshold_raw)) {
            ++features->high_sample_count;
        }
        if (samples[index] <= lower_rail_limit) {
            ++features->low_rail_count;
        }
        if (samples[index] >= upper_rail_limit) {
            ++features->high_rail_count;
        }
        if (absolute_centered > features->peak_deviation) {
            features->peak_deviation = absolute_centered;
        }
        features->sum_squared +=
            (uint64_t)absolute_centered * absolute_centered;

        if (index > 0U) {
            int32_t step = (int32_t)samples[index] -
                (int32_t)samples[index - 1U];
            uint32_t absolute_step = (step < 0)
                ? (uint32_t)(-step)
                : (uint32_t)step;

            if (previous_step_valid) {
                int32_t second_difference = step - previous_step;
                uint32_t absolute_second_difference =
                    (second_difference < 0)
                        ? (uint32_t)(-second_difference)
                        : (uint32_t)second_difference;

                features->sum_absolute_second_differences +=
                    absolute_second_difference;
            }
            previous_step = step;
            previous_step_valid = true;
            features->sum_absolute_steps += absolute_step;
            features->sum_squared_steps +=
                (uint64_t)absolute_step * absolute_step;
            if (absolute_step > features->maximum_step) {
                features->maximum_step = absolute_step;
            }
        }
    }
    return true;
}

/* 共享 FFT 区被覆盖前，把窗口末尾原样复制到单份暂存区。 */
static void WaveformMeasurementRetainSamples(
    WaveformMeasurementInput_e input,
    const uint16_t *samples, size_t sample_count)
{
    size_t retained_count;
    size_t source_offset;
    size_t index;

    if (!WaveformMeasurementInputIsValid(input) ||
        (samples == NULL) || (sample_count == 0U)) {
        return;
    }
    retained_count =
        (sample_count < WAVEFORM_MEASUREMENT_RETAINED_SAMPLE_COUNT)
            ? sample_count
            : WAVEFORM_MEASUREMENT_RETAINED_SAMPLE_COUNT;
    source_offset = sample_count - retained_count;
    for (index = 0U; index < retained_count; ++index) {
        waveform_measurement_retained_staging[index] =
            samples[source_offset + index];
    }
}

/* 只有整帧处理成功后才替换已发布结果对应的最后 128 点。 */
static void WaveformMeasurementCommitRetainedSamples(
    WaveformMeasurementInput_e input, size_t sample_count)
{
    uint16_t *destination =
        WaveformMeasurementGetRetainedSampleBuffer(input);
    size_t retained_count =
        (sample_count < WAVEFORM_MEASUREMENT_RETAINED_SAMPLE_COUNT)
            ? sample_count
            : WAVEFORM_MEASUREMENT_RETAINED_SAMPLE_COUNT;
    size_t index;

    if (destination == NULL) {
        return;
    }
    for (index = 0U; index < retained_count; ++index) {
        destination[index] =
            waveform_measurement_retained_staging[index];
    }
}

/* 只由持有者归还共享 FFT/ADC 工作区，重复释放不会触碰全局工作区。 */
static void WaveformMeasurementReleaseFFTWorkspace(
    WaveformMeasurementInput_e input)
{
    if (!WaveformMeasurementInputIsValid(input) ||
        !waveform_measurement_fft_workspace_reserved[input]) {
        return;
    }
    waveform_measurement_fft_workspace_reserved[input] = false;
    waveform_measurement_capture_samples[input] = NULL;
    FFTAnalysisReleaseADCCaptureBuffer();
}

static ADCSamplingInput_e WaveformMeasurementMapADCInput(
    WaveformMeasurementInput_e input)
{
    return (input == WAVEFORM_MEASUREMENT_INPUT_PA21)
               ? ADC_SAMPLING_INPUT_PA21
               : ADC_SAMPLING_INPUT_PA27;
}

static FFTAnalysisInput_e WaveformMeasurementMapFFTInput(
    WaveformMeasurementInput_e input)
{
    return (input == WAVEFORM_MEASUREMENT_INPUT_PA21)
               ? FFT_ANALYSIS_INPUT_PA21
               : FFT_ANALYSIS_INPUT_PA27;
}

static AnalogCaptureInput_e WaveformMeasurementMapCaptureInput(
    WaveformMeasurementInput_e input)
{
    return (input == WAVEFORM_MEASUREMENT_INPUT_PA21)
               ? ANALOG_CAPTURE_INPUT_PA21
               : ANALOG_CAPTURE_INPUT_PA27;
}

/* 占空比暂以 min/max 中点为阈值，统计整个数据块的高电平比例。 */
static bool WaveformMeasurementCalculate(
    WaveformMeasurementInput_e input,
    const WaveformMeasurementTimeFeatures *features,
    size_t sample_count,
    uint32_t sample_rate_hz,
    const FFTAnalysisResult *fft_result,
    const AnalogCaptureMeasurement *capture_result,
    WaveformMeasurement *measurement)
{
    uint16_t minimum_raw;
    uint16_t maximum_raw;
    uint16_t average_raw;
    uint32_t high_sample_count;

    if (!WaveformMeasurementInputIsValid(input) ||
        (features == NULL) || (sample_count == 0U) ||
        (fft_result == NULL) || (measurement == NULL)) {
        return false;
    }

    minimum_raw = features->minimum_raw;
    maximum_raw = features->maximum_raw;
    average_raw = features->average_raw;
    high_sample_count = features->high_sample_count;

    *measurement = (WaveformMeasurement){0};
    measurement->source = input;
    measurement->sample_count = (uint16_t)sample_count;
    measurement->sample_rate_hz = sample_rate_hz;
    measurement->frequency_scale_numerator =
        WaveformMeasurementGetInputFrequencyScaleNumerator(input);
    measurement->frequency_scale_denominator =
        WaveformMeasurementGetInputFrequencyScaleDenominator(input);
    measurement->frequency_source =
        WAVEFORM_MEASUREMENT_FREQUENCY_SOURCE_NONE;
    measurement->status = WAVEFORM_MEASUREMENT_STATUS_PARTIAL;

    if (!ADCSamplingConvertRawToMillivolts(
            WaveformMeasurementMapADCInput(input), minimum_raw,
            &measurement->minimum_millivolts) ||
        !ADCSamplingConvertRawToMillivolts(
            WaveformMeasurementMapADCInput(input), maximum_raw,
            &measurement->maximum_millivolts) ||
        !ADCSamplingConvertRawToMillivolts(
            WaveformMeasurementMapADCInput(input), average_raw,
            &measurement->average_millivolts)) {
        return false;
    }

    measurement->peak_to_peak_millivolts =
        measurement->maximum_millivolts -
        measurement->minimum_millivolts;
    measurement->duty_cycle_permyriad =
        (uint16_t)(((high_sample_count *
            WAVEFORM_MEASUREMENT_DUTY_SCALE) +
            (sample_count / 2U)) /
            sample_count);
    measurement->valid_mask =
        WAVEFORM_MEASUREMENT_VALID_MINIMUM |
        WAVEFORM_MEASUREMENT_VALID_MAXIMUM |
        WAVEFORM_MEASUREMENT_VALID_PEAK_TO_PEAK |
        WAVEFORM_MEASUREMENT_VALID_AVERAGE;
    measurement->waveform_type = WaveformMeasurementClassifyWaveform(
        features, sample_count, fft_result);
    if (measurement->waveform_type !=
        WAVEFORM_MEASUREMENT_WAVEFORM_UNKNOWN) {
        measurement->valid_mask |=
            WAVEFORM_MEASUREMENT_VALID_WAVEFORM_TYPE;
    }

    if ((maximum_raw - minimum_raw) <
        WAVEFORM_MEASUREMENT_MINIMUM_P2P_RAW) {
        measurement->frequency_millihz = 0UL;
        measurement->period_microseconds = 0UL;
        measurement->duty_cycle_permyriad = 0U;
        measurement->status = WAVEFORM_MEASUREMENT_STATUS_NO_SIGNAL;
    }
    else {
        /* 占空比来自本 ADC 块的中点阈值统计，与频率来源无关。 */
        measurement->valid_mask |=
            WAVEFORM_MEASUREMENT_VALID_DUTY_CYCLE;
    }

    if (measurement->status == WAVEFORM_MEASUREMENT_STATUS_NO_SIGNAL) {
        return true;
    }
    /*
     * 低频优先使用高分辨率的硬件 Capture。高频时中断延迟可能
     * 使它取到非相邻边沿，因此必须与同一采样窗口的 FFT 主峰基本一致。
     * 不一致时回退到 FFT，避免把错误 Capture 频率映射到 DDS。
     */
    if ((capture_result != NULL) &&
        WaveformMeasurementCaptureMatchesFFT(
            capture_result, fft_result)) {
        if (!WaveformMeasurementScaleInputFrequencyMillihz(
                input, capture_result->frequency_millihz,
                &measurement->frequency_millihz) ||
            (measurement->frequency_millihz == 0UL)) {
            return false;
        }
        measurement->period_microseconds = (uint32_t)(
            (1000000000ULL +
                (measurement->frequency_millihz / 2UL)) /
            measurement->frequency_millihz);
        measurement->frequency_source =
            WAVEFORM_MEASUREMENT_FREQUENCY_SOURCE_CAPTURE;
        measurement->valid_mask |=
            WAVEFORM_MEASUREMENT_VALID_FREQUENCY |
            WAVEFORM_MEASUREMENT_VALID_PERIOD;
        measurement->status = WAVEFORM_MEASUREMENT_STATUS_VALID;
    }
    else if ((fft_result->peak_magnitude > 0U) &&
             (fft_result->peak_frequency_millihz > 0UL)) {
        if (!WaveformMeasurementScaleInputFrequencyMillihz(
                input, fft_result->peak_frequency_millihz,
                &measurement->frequency_millihz) ||
            (measurement->frequency_millihz == 0UL)) {
            return false;
        }
        measurement->period_microseconds = (uint32_t)(
            (1000000000ULL +
                (measurement->frequency_millihz / 2UL)) /
            measurement->frequency_millihz);
        measurement->frequency_source =
            WAVEFORM_MEASUREMENT_FREQUENCY_SOURCE_FFT;
        measurement->valid_mask |=
            WAVEFORM_MEASUREMENT_VALID_FREQUENCY |
            WAVEFORM_MEASUREMENT_VALID_PERIOD;
        measurement->status = WAVEFORM_MEASUREMENT_STATUS_VALID;
    } else {
        measurement->frequency_millihz = 0UL;
        measurement->period_microseconds = 0UL;
    }
    return true;
}

/*
 * 使用采样分布、峰值因数和压缩频谱做轻量分类。该结果用于界面提示和
 * 业务初筛，不替代示波器或完整谐波分析。
 */
static WaveformMeasurementWaveformType_e
    WaveformMeasurementClassifyWaveform(
        const WaveformMeasurementTimeFeatures *features,
        size_t sample_count,
        const FFTAnalysisResult *fft_result)
{
    uint32_t peak_to_peak_raw;
    uint32_t low_rail_count;
    uint32_t high_rail_count;
    uint32_t peak_deviation;
    uint32_t maximum_step;
    uint64_t sum_squared;
    uint64_t sum_absolute_steps;
    uint64_t sum_squared_steps;
    uint64_t sum_absolute_second_differences;
    uint64_t crest_squared_scaled;
    uint64_t step_uniformity_scaled = UINT64_MAX;
    uint32_t curvature_scaled = UINT32_MAX;
    uint32_t triangle_curvature_limit = 0UL;
    uint32_t low_rail_ratio;
    uint32_t high_rail_ratio;
    uint32_t total_rail_ratio;
    uint32_t spectrum_sum = 0UL;
    uint32_t spectral_dominance = 0UL;
    uint32_t third_harmonic_ratio = 0UL;
    size_t index;

    if ((features == NULL) || (sample_count < 2U) ||
        (fft_result == NULL) ||
        (features->maximum_raw < features->minimum_raw)) {
        return WAVEFORM_MEASUREMENT_WAVEFORM_UNKNOWN;
    }
    peak_to_peak_raw =
        features->maximum_raw - features->minimum_raw;
    if (peak_to_peak_raw < WAVEFORM_MEASUREMENT_MINIMUM_P2P_RAW) {
        return WAVEFORM_MEASUREMENT_WAVEFORM_DC;
    }
    low_rail_count = features->low_rail_count;
    high_rail_count = features->high_rail_count;
    peak_deviation = features->peak_deviation;
    maximum_step = features->maximum_step;
    sum_squared = features->sum_squared;
    sum_absolute_steps = features->sum_absolute_steps;
    sum_squared_steps = features->sum_squared_steps;
    sum_absolute_second_differences =
        features->sum_absolute_second_differences;

    if ((sum_squared == 0ULL) || (peak_deviation == 0UL)) {
        return WAVEFORM_MEASUREMENT_WAVEFORM_DC;
    }

    /*
     * 理想方波的峰值因数平方接近 1，正弦波接近 2。先计算该特征，
     * 再结合靠近上下电平的样本占比判断方波，避免峰顶变化较慢或
     * 轻微削顶的正弦波被提前误判。
     */
    crest_squared_scaled =
        (((uint64_t)peak_deviation * peak_deviation * sample_count *
             WAVEFORM_MEASUREMENT_CLASSIFY_SCALE) +
            (sum_squared / 2ULL)) /
        sum_squared;
    low_rail_ratio = (uint32_t)(
        ((uint64_t)low_rail_count *
            WAVEFORM_MEASUREMENT_CLASSIFY_SCALE) /
        sample_count);
    high_rail_ratio = (uint32_t)(
        ((uint64_t)high_rail_count *
            WAVEFORM_MEASUREMENT_CLASSIFY_SCALE) /
        sample_count);
    total_rail_ratio = low_rail_ratio + high_rail_ratio;

    if ((crest_squared_scaled <=
             WAVEFORM_MEASUREMENT_CLASSIFY_SQUARE_CREST_SQUARED_MAXIMUM) &&
        (total_rail_ratio >=
            WAVEFORM_MEASUREMENT_CLASSIFY_SQUARE_RAIL_MINIMUM) &&
        (low_rail_ratio >=
            WAVEFORM_MEASUREMENT_CLASSIFY_SQUARE_SIDE_MINIMUM) &&
        (high_rail_ratio >=
            WAVEFORM_MEASUREMENT_CLASSIFY_SQUARE_SIDE_MINIMUM)) {
        return WAVEFORM_MEASUREMENT_WAVEFORM_SQUARE;
    }
    if ((crest_squared_scaled >
             WAVEFORM_MEASUREMENT_CLASSIFY_SINE_CREST_SQUARED_MAXIMUM) &&
        (crest_squared_scaled <=
             WAVEFORM_MEASUREMENT_CLASSIFY_TRIANGLE_CREST_SQUARED_MAXIMUM) &&
        (sum_absolute_steps > 0ULL) &&
        ((uint64_t)maximum_step * (sample_count - 1U) >
            sum_absolute_steps *
                WAVEFORM_MEASUREMENT_CLASSIFY_SAWTOOTH_JUMP_FACTOR)) {
        return WAVEFORM_MEASUREMENT_WAVEFORM_SAWTOOTH;
    }

    for (index = 1U; index < FFT_ANALYSIS_BIN_COUNT; ++index) {
        spectrum_sum += fft_result->magnitudes[index];
    }
    if (spectrum_sum > 0UL) {
        spectral_dominance = (uint32_t)(
            (((uint64_t)fft_result->peak_magnitude *
                 WAVEFORM_MEASUREMENT_CLASSIFY_SCALE) +
                (spectrum_sum / 2UL)) /
            spectrum_sum);
    }
    if (sum_absolute_steps > 0ULL) {
        step_uniformity_scaled =
            ((sum_squared_steps * (sample_count - 1U) *
                 WAVEFORM_MEASUREMENT_CLASSIFY_SCALE) +
                ((sum_absolute_steps * sum_absolute_steps) / 2ULL)) /
            (sum_absolute_steps * sum_absolute_steps);
        curvature_scaled = (uint32_t)(
            ((sum_absolute_second_differences *
                 WAVEFORM_MEASUREMENT_CLASSIFY_SCALE) +
                (sum_absolute_steps / 2ULL)) /
            sum_absolute_steps);
    }
    if ((fft_result->point_count > 0U) &&
        (fft_result->peak_bin >=
            WAVEFORM_MEASUREMENT_CLASSIFY_TRIANGLE_CURVATURE_MINIMUM_BIN) &&
        (fft_result->peak_bin <=
            ((fft_result->point_count +
                 (WAVEFORM_MEASUREMENT_CLASSIFY_TRIANGLE_CURVATURE_MINIMUM_SAMPLES - 1U)) /
                WAVEFORM_MEASUREMENT_CLASSIFY_TRIANGLE_CURVATURE_MINIMUM_SAMPLES))) {
        triangle_curvature_limit = (uint32_t)(
            (((uint64_t)WAVEFORM_MEASUREMENT_CLASSIFY_TRIANGLE_CURVATURE_FACTOR *
                 fft_result->peak_bin) +
                (fft_result->point_count / 2U)) /
            fft_result->point_count);
    }
    if ((fft_result->peak_bin > 0U) &&
        (fft_result->point_count >= 2U) &&
        (fft_result->peak_magnitude > 0U)) {
        uint32_t point_count = fft_result->point_count;
        uint32_t positive_bin_count = fft_result->point_count / 2U;
        uint32_t third_harmonic_bin =
            ((uint32_t)fft_result->peak_bin * 3UL) % point_count;

        if (third_harmonic_bin > positive_bin_count) {
            third_harmonic_bin = point_count - third_harmonic_bin;
        }

        if ((positive_bin_count > 0UL) &&
            (third_harmonic_bin > 0UL) &&
            (third_harmonic_bin <= positive_bin_count)) {
            uint32_t fundamental_compressed_bin = (uint32_t)(
                (((uint64_t)fft_result->peak_bin *
                      (FFT_ANALYSIS_BIN_COUNT - 1U)) +
                    (positive_bin_count - 1UL)) /
                positive_bin_count);
            uint32_t compressed_bin = (uint32_t)(
                (((uint64_t)third_harmonic_bin *
                      (FFT_ANALYSIS_BIN_COUNT - 1U)) +
                    (positive_bin_count - 1UL)) /
                positive_bin_count);

            if ((compressed_bin > 0UL) &&
                (compressed_bin < FFT_ANALYSIS_BIN_COUNT) &&
                (compressed_bin != fundamental_compressed_bin)) {
                third_harmonic_ratio = (uint32_t)(
                    (((uint64_t)fft_result->magnitudes[compressed_bin] *
                         WAVEFORM_MEASUREMENT_CLASSIFY_SCALE) +
                        (fft_result->peak_magnitude / 2U)) /
                    fft_result->peak_magnitude);
            }
        }
    }
    /*
     * 三角波的相邻采样斜率大部分保持一致，并含有约为基波 1/9 的
     * 三次谐波；超过 Nyquist 时按实际采样后的混叠频率寻找该分量。
     * 正弦波斜率持续变化且理想情况下没有三次谐波。
     */
    if ((third_harmonic_ratio >=
             WAVEFORM_MEASUREMENT_CLASSIFY_TRIANGLE_THIRD_HARMONIC_MINIMUM) &&
        (step_uniformity_scaled <=
            WAVEFORM_MEASUREMENT_CLASSIFY_TRIANGLE_STEP_UNIFORMITY_MAXIMUM)) {
        return WAVEFORM_MEASUREMENT_WAVEFORM_TRIANGLE;
    }
    /*
     * 二阶差分表示波形的弯曲程度。三角波除波峰、波谷外基本是直线，
     * 归一化曲率明显低于同频正弦波。每周期少于约 5 点时两者曲率会
     * 退化为相近结果，因此高频区域禁用该规则，避免 400 kHz 正弦误判。
     */
    if ((triangle_curvature_limit > 0UL) &&
        (crest_squared_scaled >
            WAVEFORM_MEASUREMENT_CLASSIFY_SQUARE_CREST_SQUARED_MAXIMUM) &&
        (curvature_scaled <= triangle_curvature_limit)) {
        return WAVEFORM_MEASUREMENT_WAVEFORM_TRIANGLE;
    }
    /* 三角波本身含有谐波，完成三角波判断后才能归入 HARMONIC。 */
    if (spectral_dominance <
        WAVEFORM_MEASUREMENT_CLASSIFY_SPECTRAL_MINIMUM) {
        return WAVEFORM_MEASUREMENT_WAVEFORM_HARMONIC;
    }
    /*
     * 正弦波在波峰和波谷附近变化较慢，因此落在幅值两端各 10% 内的
     * 样本通常明显多于线性变化的三角波。该分布特征用于容忍直流偏置、
     * 非整周期窗口和轻微幅度失真导致的峰值因数偏差。
     */
    if ((crest_squared_scaled >
             WAVEFORM_MEASUREMENT_CLASSIFY_SQUARE_CREST_SQUARED_MAXIMUM) &&
        (crest_squared_scaled <=
            WAVEFORM_MEASUREMENT_CLASSIFY_SINE_RAIL_CREST_SQUARED_MAXIMUM) &&
        (total_rail_ratio >=
            WAVEFORM_MEASUREMENT_CLASSIFY_SINE_RAIL_MINIMUM) &&
        (low_rail_ratio >=
            WAVEFORM_MEASUREMENT_CLASSIFY_SQUARE_SIDE_MINIMUM) &&
        (high_rail_ratio >=
            WAVEFORM_MEASUREMENT_CLASSIFY_SQUARE_SIDE_MINIMUM)) {
        return WAVEFORM_MEASUREMENT_WAVEFORM_SINE;
    }
    if ((crest_squared_scaled >=
             WAVEFORM_MEASUREMENT_CLASSIFY_SINE_CREST_SQUARED_MINIMUM) &&
        (crest_squared_scaled <=
             WAVEFORM_MEASUREMENT_CLASSIFY_SINE_CREST_SQUARED_MAXIMUM)) {
        return WAVEFORM_MEASUREMENT_WAVEFORM_SINE;
    }
    if (crest_squared_scaled <=
        WAVEFORM_MEASUREMENT_CLASSIFY_TRIANGLE_CREST_SQUARED_MAXIMUM) {
        return WAVEFORM_MEASUREMENT_WAVEFORM_TRIANGLE;
    }
    return WAVEFORM_MEASUREMENT_WAVEFORM_HARMONIC;
}

/* 超过三个最近周期仍无新边沿时，认为对应引脚的捕获结果已失效。 */
static bool WaveformMeasurementCaptureIsFresh(
    const AnalogCaptureMeasurement *capture_result,
    TickType_t update_time, TickType_t current_time)
{
    uint64_t timeout_milliseconds;
    TickType_t timeout_ticks;

    if ((capture_result == NULL) ||
        (capture_result->period_microseconds == 0UL)) {
        return false;
    }

    timeout_milliseconds =
        (((uint64_t)capture_result->period_microseconds *
              WAVEFORM_MEASUREMENT_CAPTURE_TIMEOUT_PERIODS) +
            999ULL) /
        1000ULL;
    if (timeout_milliseconds <
        WAVEFORM_MEASUREMENT_CAPTURE_MINIMUM_TIMEOUT_MS) {
        timeout_milliseconds =
            WAVEFORM_MEASUREMENT_CAPTURE_MINIMUM_TIMEOUT_MS;
    }

    timeout_ticks = pdMS_TO_TICKS((uint32_t)timeout_milliseconds);
    if (timeout_ticks == 0U) {
        timeout_ticks = 1U;
    }
    return (TickType_t)(current_time - update_time) <= timeout_ticks;
}

/*
 * FFT 主峰低于第 8 bin 时采样窗口内周期太少，仍信任 Capture。
 * 更高频率要求两者差异不超过 2 个 FFT bin 或 2%中的较大值。
 */
static bool WaveformMeasurementCaptureMatchesFFT(
    const AnalogCaptureMeasurement *capture_result,
    const FFTAnalysisResult *fft_result)
{
    uint32_t frequency_difference;
    uint32_t bin_tolerance_millihz;
    uint32_t percentage_tolerance_millihz;
    uint32_t tolerance_millihz;

    if ((capture_result == NULL) ||
        (capture_result->frequency_millihz == 0UL) ||
        (capture_result->period_microseconds == 0UL)) {
        return false;
    }
    if ((fft_result == NULL) || (fft_result->peak_magnitude == 0U) ||
        (fft_result->peak_frequency_millihz == 0UL) ||
        (fft_result->sample_rate_hz == 0UL) ||
        (fft_result->point_count == 0U)) {
        return true;
    }
    if (fft_result->peak_bin <
        WAVEFORM_MEASUREMENT_CAPTURE_FFT_MINIMUM_RELIABLE_BIN) {
        return true;
    }

    frequency_difference =
        (capture_result->frequency_millihz >=
            fft_result->peak_frequency_millihz)
            ? capture_result->frequency_millihz -
                  fft_result->peak_frequency_millihz
            : fft_result->peak_frequency_millihz -
                  capture_result->frequency_millihz;
    bin_tolerance_millihz = (uint32_t)(
        ((((uint64_t)fft_result->sample_rate_hz * 1000ULL) +
              (fft_result->point_count - 1U)) /
             fft_result->point_count) *
        WAVEFORM_MEASUREMENT_CAPTURE_FFT_TOLERANCE_BINS);
    percentage_tolerance_millihz = (uint32_t)(
        (((uint64_t)fft_result->peak_frequency_millihz *
             WAVEFORM_MEASUREMENT_CAPTURE_FFT_TOLERANCE_PERMYRIAD) +
            (WAVEFORM_MEASUREMENT_DUTY_SCALE / 2UL)) /
        WAVEFORM_MEASUREMENT_DUTY_SCALE);
    tolerance_millihz =
        (bin_tolerance_millihz >= percentage_tolerance_millihz)
            ? bin_tolerance_millihz
            : percentage_tolerance_millihz;
    return frequency_difference <= tolerance_millihz;
}

/*
 * 持锁提交结果和订阅表快照，随后在锁外逐个回调，防止观察者重入读取接口
 * 时与本模块互相等待。
 */
static void WaveformMeasurementPublish(
    const WaveformMeasurement *measurement,
    WaveformMeasurementInput_e input)
{
    WaveformMeasurement published_measurement;
    WaveformMeasurementResultSubscriber subscribers[
        WAVEFORM_MEASUREMENT_RESULT_SUBSCRIBER_COUNT];
    size_t index;

    if ((measurement == NULL) ||
        !WaveformMeasurementInputIsValid(input) ||
        (waveform_measurement_mutex == NULL) ||
        (xSemaphoreTake(waveform_measurement_mutex,
             portMAX_DELAY) != pdPASS)) {
        return;
    }

    waveform_measurement_results[input] = *measurement;
    waveform_measurement_results[input].timestamp_ticks =
        (uint32_t)xTaskGetTickCount();
    waveform_measurement_results[input].sequence =
        ++waveform_measurement_result_sequences[input];
    waveform_measurement_result_ready[input] = true;
    published_measurement = waveform_measurement_results[input];
    for (index = 0U;
         index < WAVEFORM_MEASUREMENT_RESULT_SUBSCRIBER_COUNT;
         ++index) {
        subscribers[index] =
            waveform_measurement_result_subscribers[index];
    }
    (void)xSemaphoreGive(waveform_measurement_mutex);

    for (index = 0U;
         index < WAVEFORM_MEASUREMENT_RESULT_SUBSCRIBER_COUNT;
         ++index) {
        if (subscribers[index].callback != NULL) {
            subscribers[index].callback(input,
                &published_measurement, subscribers[index].context);
        }
    }
}

static void WaveformMeasurementDebugSend(
    const uint8_t *data, size_t size)
{
    if (WAVEFORM_MEASUREMENT_DEBUG_OUTPUT_ENABLED != 0U) {
        (void)SerialCommunicationUART0Send(data, size);
    }
}

#endif /* APP_ENABLE_WAVEFORM_MEASUREMENT */
