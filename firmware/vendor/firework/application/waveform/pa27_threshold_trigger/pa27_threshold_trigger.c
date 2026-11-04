/*
 * PA27 阈值触发模块由 ADC 事件回调负责“发现触发”，由任务负责“完成采集和保存”。
 * 回调与任务之间通过通知位协作，避免在中断上下文执行 Flash 操作。
 */
#include "application/waveform/pa27_threshold_trigger/pa27_threshold_trigger.h"

#include "application/app_config.h"

#if APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U

#include <stddef.h>

#include "FreeRTOS.h"
#include "task.h"

#include "application/task/task_manager.h"
#include "application/waveform/arbitrary_waveform/arbitrary_waveform.h"
#include "application/waveform/waveform_measurement/waveform_measurement.h"
#include "modules/adc/adc_sampling.h"
#include "modules/dac/dac_output.h"

#define PA27_TRIGGER_RAW_MAXIMUM  (4095U)
#define PA27_TRIGGER_REFERENCE_MV (3300U)

/* ISR 与任务通过独立通知位合并事件，避免连续事件覆盖尚未处理的通知。 */
#define PA27_TRIGGER_NOTIFY_ARM        (1UL << 0U)
#define PA27_TRIGGER_NOTIFY_CAPTURED   (1UL << 1U)
#define PA27_TRIGGER_NOTIFY_REARMED    (1UL << 2U)
#define PA27_TRIGGER_NOTIFY_CANCEL     (1UL << 3U)

/*
 * armed/status 由公开接口、任务和 ISR 共同观察；任务负责所有 Flash 写入，
 * ISR 只更新轻量状态并发送通知，取消接口负责主动结束底层捕获。
 */
static TaskHandle_t pa27_trigger_task_handle;
static volatile bool pa27_trigger_initialized;
static volatile bool pa27_trigger_armed;
static volatile bool pa27_trigger_cancel_requested;
/* 当前一次触发完成后使用的槽位；成功回落后自动递增并循环。 */
static volatile uint8_t pa27_trigger_current_slot;
static volatile uint8_t pa27_trigger_last_saved_slot;
static volatile PA27ThresholdTriggerMode_e pa27_trigger_mode =
    PA27_THRESHOLD_TRIGGER_MODE_CONTINUOUS;
static volatile PA27ThresholdTriggerStatus_e pa27_trigger_status =
    PA27_THRESHOLD_TRIGGER_IDLE;
static volatile uint32_t pa27_trigger_sequence;

static void PA27ThresholdTriggerTask(void *argument);
/* ADC 阈值回调只映射事件并唤醒任务，禁止在 ISR 中分析或写 Flash。 */
static void PA27ThresholdTriggerCaptureEventFromISR(
    ADCSamplingInput_e input, ADCSamplingThresholdEvent_e event,
    uint32_t sequence, void *context);
static uint16_t PA27ThresholdTriggerMillivoltsToRaw(uint32_t millivolts);
static void PA27ThresholdTriggerSetIdleAfterCancel(void);
static bool PA27ThresholdTriggerStartCapture(
    uint16_t *buffer, size_t capture_count, uint16_t threshold_raw);

bool PA27ThresholdTriggerInit(void)
{
    if (pa27_trigger_initialized) {
        return true;
    }
    if (!ArbitraryWaveformIsInitialized() ||
        (DACOutputGetCustomWaveformBuffer() == NULL)) {
        return false;
    }
    pa27_trigger_task_handle = ApplicationTaskCreate(
        APPLICATION_TASK_PA27_THRESHOLD_TRIGGER,
        PA27ThresholdTriggerTask, NULL);
    if (pa27_trigger_task_handle == NULL) {
        return false;
    }
    pa27_trigger_initialized = true;
    return true;
}

bool PA27ThresholdTriggerSetMode(PA27ThresholdTriggerMode_e mode)
{
    if (!pa27_trigger_initialized ||
        (mode < PA27_THRESHOLD_TRIGGER_MODE_OFF) ||
        (mode > PA27_THRESHOLD_TRIGGER_MODE_CONTINUOUS)) {
        return false;
    }

    taskENTER_CRITICAL();
    pa27_trigger_mode = mode;
    taskEXIT_CRITICAL();
    if (mode == PA27_THRESHOLD_TRIGGER_MODE_OFF) {
        return PA27ThresholdTriggerCancel();
    }
    return true;
}

PA27ThresholdTriggerMode_e PA27ThresholdTriggerGetMode(void)
{
    return pa27_trigger_mode;
}

bool PA27ThresholdTriggerIsActive(void)
{
    return pa27_trigger_initialized && pa27_trigger_armed;
}

bool PA27ThresholdTriggerArm(uint8_t slot_id)
{
    if (!pa27_trigger_initialized ||
        (slot_id >= APP_ARBITRARY_WAVEFORM_SLOT_COUNT) ||
        (xTaskGetSchedulerState() != taskSCHEDULER_RUNNING)) {
        return false;
    }
    taskENTER_CRITICAL();
    if (pa27_trigger_armed ||
        (pa27_trigger_mode == PA27_THRESHOLD_TRIGGER_MODE_OFF)) {
        taskEXIT_CRITICAL();
        return false;
    }
    /* slot_id 是本轮连续采集的起始槽位，后续由模块自动轮换。 */
    pa27_trigger_current_slot = slot_id;
    pa27_trigger_cancel_requested = false;
    pa27_trigger_armed = true;
    pa27_trigger_status = PA27_THRESHOLD_TRIGGER_WAITING;
    taskEXIT_CRITICAL();
    (void)xTaskNotify(pa27_trigger_task_handle,
        PA27_TRIGGER_NOTIFY_ARM, eSetBits);
    return true;
}

bool PA27ThresholdTriggerCancel(void)
{
    if (!pa27_trigger_initialized) {
        return false;
    }
    taskENTER_CRITICAL();
    pa27_trigger_cancel_requested = true;
    pa27_trigger_armed = false;
    pa27_trigger_status = PA27_THRESHOLD_TRIGGER_IDLE;
    taskEXIT_CRITICAL();
    (void)ADCSamplingFinishThresholdInputCapture(
        ADC_SAMPLING_INPUT_PA27);
    (void)xTaskNotify(pa27_trigger_task_handle,
        PA27_TRIGGER_NOTIFY_CANCEL, eSetBits);
    return true;
}

PA27ThresholdTriggerStatus_e PA27ThresholdTriggerGetStatus(void)
{
    return pa27_trigger_status;
}

uint8_t PA27ThresholdTriggerGetLastSavedSlot(void)
{
    return pa27_trigger_last_saved_slot;
}

static void PA27ThresholdTriggerTask(void *argument)
{
    uint16_t *buffer;
    const size_t capture_count =
        (size_t)APP_PA27_TRIGGER_CAPTURE_DURATION_US *
        APP_PA27_TRIGGER_SAMPLE_RATE_HZ / 1000000UL;
    const uint16_t threshold_raw =
        PA27ThresholdTriggerMillivoltsToRaw(
            APP_PA27_TRIGGER_THRESHOLD_MILLIVOLTS);

    (void)argument;
    /* 采集时长和采样率在任务启动时换算为固定点数，后续统一做边界检查。 */
    buffer = DACOutputGetCustomWaveformBuffer();

    for (;;) {
        uint32_t notification;

        /* ARM、取消和采集阶段事件都通过任务通知传递，任务本身无需轮询。 */
        (void)xTaskNotifyWait(0UL, UINT32_MAX, &notification,
            portMAX_DELAY);
        if ((notification & PA27_TRIGGER_NOTIFY_CANCEL) != 0UL) {
            /* 取消通知优先清理状态，避免随后误启动已经取消的采集。 */
            PA27ThresholdTriggerSetIdleAfterCancel();
        }
        if ((notification & PA27_TRIGGER_NOTIFY_ARM) == 0UL) {
            continue;
        }
        if (!pa27_trigger_armed || pa27_trigger_cancel_requested ||
            (buffer == NULL) || (capture_count < 2U) ||
            (capture_count > APP_ARBITRARY_WAVEFORM_MAX_SAMPLES)) {
            continue;
        }

        if (!PA27ThresholdTriggerStartCapture(
                buffer, capture_count, threshold_raw)) {
            taskENTER_CRITICAL();
            pa27_trigger_armed = false;
            pa27_trigger_status = PA27_THRESHOLD_TRIGGER_ERROR;
            taskEXIT_CRITICAL();
            /* 启动失败后标记错误，等待下一次 ARM 请求重新尝试。 */
            continue;
        }

        {
            bool saved = false;
            bool rearmed = false;
            uint8_t slot_id = pa27_trigger_current_slot;

            /* 每次保存并确认回落后，继续等待下一次触发并轮换槽位。 */
            while (pa27_trigger_armed &&
                   !pa27_trigger_cancel_requested) {
                bool stop = false;

                (void)xTaskNotifyWait(0UL, UINT32_MAX, &notification,
                    portMAX_DELAY);
                if ((notification & PA27_TRIGGER_NOTIFY_CANCEL) != 0UL) {
                    stop = true;
                }
                if (!stop &&
                    ((notification & PA27_TRIGGER_NOTIFY_CAPTURED) != 0UL)) {
                    /* 采集完成后立即把指定窗口保存到请求的 Flash 槽位。 */
                    if (!ArbitraryWaveformSave(
                            slot_id, buffer, (uint16_t)capture_count,
                            APP_PA27_TRIGGER_SAMPLE_RATE_HZ, 1U)) {
                        stop = true;
                    } else {
                        /* 保存原始数据后复用统一模块计算 PA27 参数和类型。 */
                        (void)WaveformMeasurementAnalyzeExternalSamples(
                            WAVEFORM_MEASUREMENT_INPUT_PA27, buffer,
                            capture_count, APP_PA27_TRIGGER_SAMPLE_RATE_HZ,
                            pa27_trigger_sequence + 1UL);
                        saved = true;
                        pa27_trigger_status =
                            PA27_THRESHOLD_TRIGGER_WAITING_LOW;
                    }
                }
                if ((notification & PA27_TRIGGER_NOTIFY_REARMED) != 0UL) {
                    /* 信号回到低电平后才允许本次触发流程正式结束。 */
                    rearmed = true;
                }
                if (stop) {
                    (void)ADCSamplingFinishThresholdInputCapture(
                        ADC_SAMPLING_INPUT_PA27);
                    taskENTER_CRITICAL();
                    pa27_trigger_armed = false;
                    pa27_trigger_status =
                        pa27_trigger_cancel_requested
                            ? PA27_THRESHOLD_TRIGGER_IDLE
                            : PA27_THRESHOLD_TRIGGER_ERROR;
                    pa27_trigger_cancel_requested = false;
                    taskEXIT_CRITICAL();
                    break;
                }
                if (saved && rearmed) {
                    bool restart_capture = false;

                    (void)ADCSamplingFinishThresholdInputCapture(
                        ADC_SAMPLING_INPUT_PA27);
                    taskENTER_CRITICAL();
                    pa27_trigger_last_saved_slot = slot_id;
                    ++pa27_trigger_sequence;
                    restart_capture =
                        (pa27_trigger_mode ==
                            PA27_THRESHOLD_TRIGGER_MODE_CONTINUOUS) &&
                        pa27_trigger_armed &&
                        !pa27_trigger_cancel_requested;
                    if (restart_capture) {
                        slot_id = (uint8_t)(slot_id + 1U);
                        if (slot_id >= APP_ARBITRARY_WAVEFORM_SLOT_COUNT) {
                            slot_id = 0U;
                        }
                        pa27_trigger_current_slot = slot_id;
                        pa27_trigger_status =
                            PA27_THRESHOLD_TRIGGER_WAITING;
                    } else {
                        pa27_trigger_armed = false;
                        pa27_trigger_status =
                            pa27_trigger_cancel_requested
                                ? PA27_THRESHOLD_TRIGGER_IDLE
                                : PA27_THRESHOLD_TRIGGER_SAVED;
                        pa27_trigger_cancel_requested = false;
                    }
                    taskEXIT_CRITICAL();

                    saved = false;
                    rearmed = false;
                    if (restart_capture &&
                        !PA27ThresholdTriggerStartCapture(
                            buffer, capture_count, threshold_raw)) {
                        taskENTER_CRITICAL();
                        pa27_trigger_armed = false;
                        pa27_trigger_status =
                            PA27_THRESHOLD_TRIGGER_ERROR;
                        taskEXIT_CRITICAL();
                        break;
                    }
                }
            }
        }
    }
}

static void PA27ThresholdTriggerCaptureEventFromISR(
    ADCSamplingInput_e input, ADCSamplingThresholdEvent_e event,
    uint32_t sequence, void *context)
{
    BaseType_t higher_priority_task_woken = pdFALSE;
    uint32_t notification;

    (void)input;
    (void)sequence;
    (void)context;
    notification = (event == ADC_SAMPLING_THRESHOLD_SIGNAL_REARMED)
        ? PA27_TRIGGER_NOTIFY_REARMED
        : PA27_TRIGGER_NOTIFY_CAPTURED;
    if (event == ADC_SAMPLING_THRESHOLD_CAPTURE_COMPLETE) {
        pa27_trigger_status = PA27_THRESHOLD_TRIGGER_CAPTURING;
    }
    (void)xTaskNotifyFromISR(pa27_trigger_task_handle, notification,
        eSetBits, &higher_priority_task_woken);
    portYIELD_FROM_ISR(higher_priority_task_woken);
}

/* 按 3.3 V/12 位满量程四舍五入换算阈值，并钳位到 ADC 有效范围。 */
static uint16_t PA27ThresholdTriggerMillivoltsToRaw(uint32_t millivolts)
{
    uint32_t raw = (millivolts * PA27_TRIGGER_RAW_MAXIMUM +
        (PA27_TRIGGER_REFERENCE_MV / 2U)) / PA27_TRIGGER_REFERENCE_MV;

    return (uint16_t)((raw > PA27_TRIGGER_RAW_MAXIMUM)
        ? PA27_TRIGGER_RAW_MAXIMUM : raw);
}

static bool PA27ThresholdTriggerStartCapture(
    uint16_t *buffer, size_t capture_count, uint16_t threshold_raw)
{
    /* 捕获期间暂停 DAC 输出，避免输出模块与 ADC 采集争用资源。 */
    (void)DACOutputStop();
    return ADCSamplingStartThresholdInputCapture(
        ADC_SAMPLING_INPUT_PA27, buffer,
        APP_ARBITRARY_WAVEFORM_MAX_SAMPLES, capture_count,
        APP_PA27_TRIGGER_SAMPLE_RATE_HZ, threshold_raw, threshold_raw,
        PA27ThresholdTriggerCaptureEventFromISR, NULL);
}

/* 仅消费仍属于当前请求的取消标志，避免迟到通知覆盖新的 Arm 状态。 */
static void PA27ThresholdTriggerSetIdleAfterCancel(void)
{
    if (!pa27_trigger_armed && pa27_trigger_cancel_requested) {
        pa27_trigger_cancel_requested = false;
        pa27_trigger_status = PA27_THRESHOLD_TRIGGER_IDLE;
    }
}

#endif /* APP_ENABLE_PA27_THRESHOLD_TRIGGER */
