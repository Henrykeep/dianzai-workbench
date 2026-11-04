/* 将两路比较器捕获统一为按输入编号访问、以工程单位表示的测量服务。 */
#include "modules/capture/analog_capture.h"

#include "application/app_config.h"

#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U

#include <stddef.h>

#include "modules/capture/capture.h"

#define ANALOG_CAPTURE_DEFAULT_THRESHOLD_MILLIVOLTS (1650U)

/* 每个统一输入保存一个固定 Capture 实例，不使用动态分配。 */
static CaptureInstance *analog_capture_inputs[ANALOG_CAPTURE_INPUT_COUNT];

static CaptureInstance *AnalogCaptureGetInstance(
    AnalogCaptureInput_e input);
static bool AnalogCaptureInputIsValid(AnalogCaptureInput_e input);

/* 默认使用约 VDDA/2 阈值，适配常见 0～3.3 V 和 0.5～2.8 V 波形。 */
bool AnalogCaptureInit(void)
{
    return AnalogCaptureInitInput(ANALOG_CAPTURE_INPUT_PA27) &&
           AnalogCaptureInitInput(ANALOG_CAPTURE_INPUT_PA21);
}

/* 注册并启动指定统一输入的 COMP + Timer 捕获。 */
bool AnalogCaptureInitInput(AnalogCaptureInput_e input)
{
    static const CaptureConfig config = {
        ANALOG_CAPTURE_DEFAULT_THRESHOLD_MILLIVOLTS,
        false
    };
    Capture_Device_e device;

    if (!AnalogCaptureInputIsValid(input)) {
        return false;
    }

    device = (input == ANALOG_CAPTURE_INPUT_PA21)
                 ? CAPTURE_DEVICE_ANALOG_INPUT_1
                 : CAPTURE_DEVICE_ANALOG_INPUT_0;
    if (analog_capture_inputs[input] == NULL) {
        analog_capture_inputs[input] = CaptureRegister(device, &config);
    }
    return (analog_capture_inputs[input] != NULL) &&
           CaptureStart(analog_capture_inputs[input]);
}

bool AnalogCaptureStart(void)
{
    AnalogCaptureInput_e input;
    bool any_registered = false;
    bool result = true;

    for (input = ANALOG_CAPTURE_INPUT_PA27;
         input < ANALOG_CAPTURE_INPUT_COUNT; ++input) {
        if (analog_capture_inputs[input] != NULL) {
            any_registered = true;
            result = AnalogCaptureStartInput(input) && result;
        }
    }
    return any_registered && result;
}

/* 聚合操作会尝试处理全部已注册输入，并在任一路失败时返回 false。 */
bool AnalogCaptureStop(void)
{
    AnalogCaptureInput_e input;
    bool any_registered = false;
    bool result = true;

    for (input = ANALOG_CAPTURE_INPUT_PA27;
         input < ANALOG_CAPTURE_INPUT_COUNT; ++input) {
        if (analog_capture_inputs[input] != NULL) {
            any_registered = true;
            result = AnalogCaptureStopInput(input) && result;
        }
    }
    return any_registered && result;
}

bool AnalogCaptureSetThresholdMillivolts(
    uint16_t threshold_millivolts)
{
    AnalogCaptureInput_e input;
    bool any_registered = false;
    bool result = true;

    for (input = ANALOG_CAPTURE_INPUT_PA27;
         input < ANALOG_CAPTURE_INPUT_COUNT; ++input) {
        if (analog_capture_inputs[input] != NULL) {
            any_registered = true;
            result = AnalogCaptureSetInputThresholdMillivolts(
                         input, threshold_millivolts) && result;
        }
    }
    return any_registered && result;
}

uint16_t AnalogCaptureGetThresholdMillivolts(void)
{
    return AnalogCaptureGetInputThresholdMillivolts(
        ANALOG_CAPTURE_INPUT_PA27);
}

/* 把 Capture Module 的定时器 tick 结果换算为微秒。 */
bool AnalogCaptureReadMeasurement(
    AnalogCaptureMeasurement *measurement)
{
    return AnalogCaptureReadInputMeasurement(
        ANALOG_CAPTURE_INPUT_PA27, measurement);
}

bool AnalogCaptureIsRunning(void)
{
    AnalogCaptureInput_e input;
    bool any_registered = false;

    for (input = ANALOG_CAPTURE_INPUT_PA27;
         input < ANALOG_CAPTURE_INPUT_COUNT; ++input) {
        if (analog_capture_inputs[input] != NULL) {
            any_registered = true;
            if (!AnalogCaptureIsInputRunning(input)) {
                return false;
            }
        }
    }
    return any_registered;
}

bool AnalogCaptureStartInput(AnalogCaptureInput_e input)
{
    CaptureInstance *instance = AnalogCaptureGetInstance(input);

    return (instance != NULL) && CaptureStart(instance);
}

bool AnalogCaptureStopInput(AnalogCaptureInput_e input)
{
    CaptureInstance *instance = AnalogCaptureGetInstance(input);

    return (instance != NULL) && CaptureStop(instance);
}

bool AnalogCaptureSetInputThresholdMillivolts(
    AnalogCaptureInput_e input, uint16_t threshold_millivolts)
{
    CaptureInstance *instance = AnalogCaptureGetInstance(input);

    return (instance != NULL) && CaptureSetThresholdMillivolts(
        instance, threshold_millivolts);
}

uint16_t AnalogCaptureGetInputThresholdMillivolts(
    AnalogCaptureInput_e input)
{
    CaptureInstance *instance = AnalogCaptureGetInstance(input);

    return (instance != NULL)
               ? CaptureGetThresholdMillivolts(instance)
               : 0U;
}

bool AnalogCaptureReadInputMeasurement(AnalogCaptureInput_e input,
    AnalogCaptureMeasurement *measurement)
{
    CaptureMeasurement capture_measurement;
    CaptureInstance *instance = AnalogCaptureGetInstance(input);
    uint32_t timer_clock_hz;

    if ((instance == NULL) || (measurement == NULL) ||
        !CaptureReadMeasurement(instance, &capture_measurement)) {
        return false;
    }

    timer_clock_hz = CaptureGetTimerClockHz(instance);
    if (timer_clock_hz == 0UL) {
        return false;
    }

    /* 使用 64 位中间值并加半个时钟周期，将 tick 四舍五入为微秒。 */
    measurement->frequency_millihz =
        capture_measurement.frequency_millihz;
    measurement->period_microseconds = (uint32_t)(
        (((uint64_t)capture_measurement.period_ticks * 1000000ULL) +
            (timer_clock_hz / 2UL)) /
        timer_clock_hz);
    measurement->edge_count = capture_measurement.edge_count;
    measurement->sequence   = capture_measurement.sequence;
    return true;
}

bool AnalogCaptureIsInputRunning(AnalogCaptureInput_e input)
{
    CaptureInstance *instance = AnalogCaptureGetInstance(input);

    return (instance != NULL) && CaptureIsRunning(instance);
}

static CaptureInstance *AnalogCaptureGetInstance(
    AnalogCaptureInput_e input)
{
    if (!AnalogCaptureInputIsValid(input)) {
        return NULL;
    }
    return analog_capture_inputs[input];
}

static bool AnalogCaptureInputIsValid(AnalogCaptureInput_e input)
{
    return (input >= ANALOG_CAPTURE_INPUT_PA27) &&
           (input < ANALOG_CAPTURE_INPUT_COUNT);
}

#endif /* APP_ENABLE_WAVEFORM_MEASUREMENT */
