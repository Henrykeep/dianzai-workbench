/* 封装 BSP 比较器/定时器捕获，并提供线程安全的周期与频率读取。 */
#include "modules/capture/capture.h"

#include "application/app_config.h"

#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U

#include <stddef.h>

#include "FreeRTOS.h"
#include "semphr.h"

#include "bsp/capture/bsp_capture.h"

/* 每个逻辑设备持有固定 BSP 实例，registered 标记完整注册状态。 */
struct CaptureInstance {
    Capture_Device_e device;
    BSPCaptureInstance *capture;
    bool registered;
};

/* 静态实例避免动态分配；共享互斥锁串行化配置和测量快照读取。 */
static CaptureInstance capture_instances[CAPTURE_DEVICE_COUNT];
static SemaphoreHandle_t capture_mutex;
static StaticSemaphore_t capture_mutex_control;

static bool CaptureIsValid(const CaptureInstance *instance);

/* 注册逻辑设备，并使用静态互斥锁保护配置和读数。 */
CaptureInstance *CaptureRegister(
    Capture_Device_e device, const CaptureConfig *config)
{
    CaptureInstance *instance;
    BSP_Capture_Device_e bsp_device;

    if ((device < CAPTURE_DEVICE_ANALOG_INPUT_0) ||
        (device >= CAPTURE_DEVICE_COUNT) || (config == NULL)) {
        return NULL;
    }

    instance = &capture_instances[device];
    if (instance->registered) {
        return instance;
    }

    if (capture_mutex == NULL) {
        capture_mutex = xSemaphoreCreateMutexStatic(
            &capture_mutex_control);
        if (capture_mutex == NULL) {
            return NULL;
        }
    }

    switch (device) {
        case CAPTURE_DEVICE_ANALOG_INPUT_0:
            bsp_device = BSP_CAPTURE_DEVICE_ANALOG_INPUT_0;
            break;

        case CAPTURE_DEVICE_ANALOG_INPUT_1:
            bsp_device = BSP_CAPTURE_DEVICE_ANALOG_INPUT_1;
            break;

        default:
            return NULL;
    }

    instance->capture = BSPCaptureRegister(bsp_device);
    if ((instance->capture == NULL) ||
        !BSPCaptureSetThresholdMillivolts(instance->capture,
            config->threshold_millivolts) ||
        (config->start_enabled &&
            !BSPCaptureStart(instance->capture))) {
        instance->capture = NULL;
        return NULL;
    }

    instance->device     = device;
    instance->registered = true;
    return instance;
}

bool CaptureStart(CaptureInstance *instance)
{
    bool result;

    if (!CaptureIsValid(instance) ||
        (xSemaphoreTake(capture_mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = BSPCaptureStart(instance->capture);
    (void)xSemaphoreGive(capture_mutex);
    return result;
}

bool CaptureStop(CaptureInstance *instance)
{
    bool result;

    if (!CaptureIsValid(instance) ||
        (xSemaphoreTake(capture_mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = BSPCaptureStop(instance->capture);
    (void)xSemaphoreGive(capture_mutex);
    return result;
}

bool CaptureSetThresholdMillivolts(
    CaptureInstance *instance, uint16_t threshold_millivolts)
{
    bool result;

    if (!CaptureIsValid(instance) ||
        (xSemaphoreTake(capture_mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = BSPCaptureSetThresholdMillivolts(
        instance->capture, threshold_millivolts);
    (void)xSemaphoreGive(capture_mutex);
    return result;
}

/* 返回 BSP 缓存的已生效阈值；实例无效时统一返回 0。 */
uint16_t CaptureGetThresholdMillivolts(
    const CaptureInstance *instance)
{
    return CaptureIsValid(instance)
               ? BSPCaptureGetThresholdMillivolts(instance->capture)
               : 0U;
}

/* 使用 64 位中间值完成频率四舍五入，避免 4 MHz×1000 溢出。 */
bool CaptureReadMeasurement(
    CaptureInstance *instance, CaptureMeasurement *measurement)
{
    BSPCaptureMeasurement bsp_measurement;
    uint32_t timer_clock_hz;
    bool result;

    if (!CaptureIsValid(instance) || (measurement == NULL) ||
        (xSemaphoreTake(capture_mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = BSPCaptureReadMeasurement(
        instance->capture, &bsp_measurement);
    timer_clock_hz = BSPCaptureGetTimerClockHz(instance->capture);
    if (result && (bsp_measurement.period_ticks > 0UL) &&
        (timer_clock_hz > 0UL)) {
        uint64_t scaled_frequency =
            ((uint64_t)timer_clock_hz * 1000ULL) +
            (bsp_measurement.period_ticks / 2UL);

        measurement->period_ticks = bsp_measurement.period_ticks;
        measurement->frequency_millihz = (uint32_t)(
            scaled_frequency / bsp_measurement.period_ticks);
        measurement->edge_count = bsp_measurement.edge_count;
        measurement->sequence   = bsp_measurement.sequence;
    }

    (void)xSemaphoreGive(capture_mutex);
    return result;
}

bool CaptureIsRunning(const CaptureInstance *instance)
{
    return CaptureIsValid(instance) &&
           BSPCaptureIsRunning(instance->capture);
}

uint32_t CaptureGetTimerClockHz(const CaptureInstance *instance)
{
    return CaptureIsValid(instance)
               ? BSPCaptureGetTimerClockHz(instance->capture)
               : 0UL;
}

static bool CaptureIsValid(const CaptureInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->device >= CAPTURE_DEVICE_ANALOG_INPUT_0) &&
           (instance->device < CAPTURE_DEVICE_COUNT) &&
           (instance->capture != NULL) && (capture_mutex != NULL);
}

#endif /* APP_ENABLE_WAVEFORM_MEASUREMENT */
