/*
 * 舵机控制层保存每个设备的目标状态，由固定周期任务逐步逼近目标角度。
 * 业务线程只提交请求；PWM 写入、平滑移动和安全停止集中在本文件处理。
 */
#include "application/control/servo_control/servo_control.h"

#include <stddef.h>

#include "FreeRTOS.h"
#include "semphr.h"
#include "task.h"

#include "application/app_config.h"
#include "application/task/task_manager.h"
#include "modules/servo/servo.h"

#define SERVO_CONTROL_TASK_PERIOD_MS (20UL)

#if APP_ENABLE_SERVO_CONTROL != 0U
/** 单只舵机的命令、输出和故障状态。 */
typedef struct {
    ServoInstance *servo;
    bool start_requested;
    bool output_enabled;
    bool faulted;
    uint16_t current_angle_degrees;
    uint16_t target_angle_degrees;
} ServoControlDeviceState;

/* 公开命令接口和 20 ms 控制任务共享每路状态，访问时统一持有静态互斥量。 */
static ServoControlDeviceState
    servo_control_devices[SERVO_CONTROL_DEVICE_COUNT];
static SemaphoreHandle_t servo_control_mutex;
static StaticSemaphore_t servo_control_mutex_control;
static bool servo_control_task_created;
static bool servo_control_ready;

static void ServoControlTask(void *argument);
static void ServoControlProcessDevice(ServoControl_Device_e device);
static bool ServoControlLock(void);
static void ServoControlUnlock(void);
static void ServoControlHandleFailure(ServoControl_Device_e device);
static void ServoControlStopAllRegistered(void);
static bool ServoControlDeviceIsConfigured(ServoControl_Device_e device);
static bool ServoControlDeviceStartsEnabled(ServoControl_Device_e device);
static bool ServoControlDeviceAutoSweepEnabled(
    ServoControl_Device_e device);
static Servo_Device_e ServoControlToServoDevice(
    ServoControl_Device_e device);
static uint16_t ServoControlGetNextAngle(
    uint16_t current_angle_degrees, uint16_t target_angle_degrees);
#endif

bool ServoControlInit(void)
{
#if APP_ENABLE_SERVO_CONTROL != 0U
    static const ServoConfig configs[SERVO_CONTROL_DEVICE_COUNT] = {
        {
            APP_SERVO_CONTROL_MINIMUM_PULSE_WIDTH_US,
            APP_SERVO_CONTROL_MAXIMUM_PULSE_WIDTH_US,
            APP_SERVO_CONTROL_MAXIMUM_ANGLE_DEGREES,
            APP_SERVO_CONTROL_OUTPUT_0_INITIAL_ANGLE_DEGREES,
            APP_SERVO_CONTROL_OUTPUT_0_START_ENABLED != 0U
        },
        {
            APP_SERVO_CONTROL_MINIMUM_PULSE_WIDTH_US,
            APP_SERVO_CONTROL_MAXIMUM_PULSE_WIDTH_US,
            APP_SERVO_CONTROL_MAXIMUM_ANGLE_DEGREES,
            APP_SERVO_CONTROL_OUTPUT_1_INITIAL_ANGLE_DEGREES,
            APP_SERVO_CONTROL_OUTPUT_1_START_ENABLED != 0U
        }
    };
    uint32_t index;

    if (servo_control_ready) {
        return true;
    }

    if (servo_control_mutex == NULL) {
        servo_control_mutex = xSemaphoreCreateMutexStatic(
            &servo_control_mutex_control);
        if (servo_control_mutex == NULL) {
            return false;
        }
    }

    /* 两路共用 TIMG7 周期，但分别使用 PA23/CCP0 和 PA24/CCP1 比较输出。 */
    for (index = 0U; index < SERVO_CONTROL_DEVICE_COUNT; ++index) {
        ServoControl_Device_e device = (ServoControl_Device_e)index;
        ServoControlDeviceState *state = &servo_control_devices[index];

        if (!ServoControlDeviceIsConfigured(device)) {
            continue;
        }

        state->servo = ServoRegister(
            ServoControlToServoDevice(device), &configs[index]);
        if (state->servo == NULL) {
            ServoControlStopAllRegistered();
            return false;
        }

        state->current_angle_degrees =
            configs[index].initial_angle_degrees;
        /* 自动模式先向最大角度移动，到达后再反向到 0°。 */
        state->target_angle_degrees =
            ServoControlDeviceAutoSweepEnabled(device)
                ? APP_SERVO_CONTROL_MAXIMUM_ANGLE_DEGREES
                : configs[index].initial_angle_degrees;
        state->start_requested =
            ServoControlDeviceStartsEnabled(device);
        state->output_enabled =
            ServoControlDeviceStartsEnabled(device);
        state->faulted = false;
    }

    if (!servo_control_task_created &&
        (ApplicationTaskCreate(APPLICATION_TASK_SERVO_CONTROL,
             ServoControlTask, NULL) == NULL)) {
        ServoControlStopAllRegistered();
        return false;
    }

    servo_control_task_created = true;
    servo_control_ready = true;
    return true;
#else
    return false;
#endif
}

bool ServoControlSetDeviceTargetAngleDegrees(
    ServoControl_Device_e device, uint16_t angle_degrees)
{
#if APP_ENABLE_SERVO_CONTROL != 0U
    if (!servo_control_ready || !ServoControlDeviceIsConfigured(device) ||
        (angle_degrees > APP_SERVO_CONTROL_MAXIMUM_ANGLE_DEGREES) ||
        !ServoControlLock()) {
        return false;
    }

    servo_control_devices[device].target_angle_degrees = angle_degrees;
    ServoControlUnlock();
    return true;
#else
    (void)device;
    (void)angle_degrees;
    return false;
#endif
}

bool ServoControlStartDevice(ServoControl_Device_e device)
{
#if APP_ENABLE_SERVO_CONTROL != 0U
    if (!servo_control_ready || !ServoControlDeviceIsConfigured(device) ||
        !ServoControlLock()) {
        return false;
    }

    /* 清除该路旧故障，硬件操作统一由控制任务执行。 */
    servo_control_devices[device].faulted = false;
    servo_control_devices[device].start_requested = true;
    ServoControlUnlock();
    return true;
#else
    (void)device;
    return false;
#endif
}

bool ServoControlStopDevice(ServoControl_Device_e device)
{
#if APP_ENABLE_SERVO_CONTROL != 0U
    if (!servo_control_ready || !ServoControlDeviceIsConfigured(device) ||
        !ServoControlLock()) {
        return false;
    }

    servo_control_devices[device].start_requested = false;
    ServoControlUnlock();
    return true;
#else
    (void)device;
    return false;
#endif
}

bool ServoControlGetDeviceStatus(
    ServoControl_Device_e device, ServoControlStatus *status)
{
#if APP_ENABLE_SERVO_CONTROL != 0U
    ServoControlDeviceState *state;

    if (!servo_control_ready || !ServoControlDeviceIsConfigured(device) ||
        (status == NULL) || !ServoControlLock()) {
        return false;
    }

    state = &servo_control_devices[device];
    status->current_angle_degrees = state->current_angle_degrees;
    status->target_angle_degrees  = state->target_angle_degrees;
    status->start_requested       = state->start_requested;
    status->output_enabled        = state->output_enabled;
    status->moving = state->output_enabled &&
                     (state->current_angle_degrees !=
                         state->target_angle_degrees);
    status->faulted = state->faulted;

    ServoControlUnlock();
    return true;
#else
    (void)device;
    (void)status;
    return false;
#endif
}

/* 以下四个接口保留原有调用方式，默认操作第一只 PA23 舵机。 */
bool ServoControlSetTargetAngleDegrees(uint16_t angle_degrees)
{
    return ServoControlSetDeviceTargetAngleDegrees(
        SERVO_CONTROL_DEVICE_OUTPUT_0, angle_degrees);
}

bool ServoControlStart(void)
{
    return ServoControlStartDevice(SERVO_CONTROL_DEVICE_OUTPUT_0);
}

bool ServoControlStop(void)
{
    return ServoControlStopDevice(SERVO_CONTROL_DEVICE_OUTPUT_0);
}

bool ServoControlGetStatus(ServoControlStatus *status)
{
    return ServoControlGetDeviceStatus(
        SERVO_CONTROL_DEVICE_OUTPUT_0, status);
}

bool ServoControlIsReady(void)
{
#if APP_ENABLE_SERVO_CONTROL != 0U
    return servo_control_ready && servo_control_task_created &&
           (servo_control_mutex != NULL) &&
           ((APP_ENABLE_SERVO_CONTROL_OUTPUT_0 == 0U) ||
               (servo_control_devices[SERVO_CONTROL_DEVICE_OUTPUT_0].servo !=
                   NULL)) &&
           ((APP_ENABLE_SERVO_CONTROL_OUTPUT_1 == 0U) ||
               (servo_control_devices[SERVO_CONTROL_DEVICE_OUTPUT_1].servo !=
                   NULL));
#else
    return false;
#endif
}

void ServoControlEnterSafeState(void)
{
#if APP_ENABLE_SERVO_CONTROL != 0U
    uint32_t index;

    if ((servo_control_mutex != NULL) && ServoControlLock()) {
        for (index = 0U; index < SERVO_CONTROL_DEVICE_COUNT; ++index) {
            servo_control_devices[index].start_requested = false;
            servo_control_devices[index].output_enabled  = false;
        }
        ServoControlUnlock();
    }
    ServoControlStopAllRegistered();
#endif
}

#if APP_ENABLE_SERVO_CONTROL != 0U
/* 单个 20 ms 任务依次推进两路舵机，避免为第二路额外消耗任务栈。 */
static void ServoControlTask(void *argument)
{
    TickType_t next_wake_time = xTaskGetTickCount();
    uint32_t index;

    (void)argument;

    for (;;) {
        /* 一个周期内依次处理已注册的舵机，每路状态彼此独立。 */
        for (index = 0U; index < SERVO_CONTROL_DEVICE_COUNT; ++index) {
            ServoControl_Device_e device = (ServoControl_Device_e)index;

            if (ServoControlDeviceIsConfigured(device)) {
                ServoControlProcessDevice(device);
            }
        }

        /* 使用绝对唤醒时间，避免单次硬件操作耗时导致周期逐渐漂移。 */
        vTaskDelayUntil(&next_wake_time,
            pdMS_TO_TICKS(SERVO_CONTROL_TASK_PERIOD_MS));
    }
}

/* 快照一只舵机的状态后执行硬件操作，避免持锁期间嵌套调用 Servo Module。 */
static void ServoControlProcessDevice(ServoControl_Device_e device)
{
    ServoControlDeviceState *state = &servo_control_devices[device];
    bool start_requested;
    bool output_enabled;
    uint16_t current_angle_degrees;
    uint16_t target_angle_degrees;

    if (!ServoControlLock()) {
        ServoControlHandleFailure(device);
        return;
    }

    start_requested = state->start_requested;
    output_enabled  = state->output_enabled;
    current_angle_degrees = state->current_angle_degrees;
    target_angle_degrees  = state->target_angle_degrees;

    /* 每一路独立在 0° 和最大角度之间翻转目标。 */
    if (ServoControlDeviceAutoSweepEnabled(device) &&
        start_requested && output_enabled &&
        (current_angle_degrees == target_angle_degrees)) {
        target_angle_degrees =
            (current_angle_degrees >=
                APP_SERVO_CONTROL_MAXIMUM_ANGLE_DEGREES)
                ? 0U
                : APP_SERVO_CONTROL_MAXIMUM_ANGLE_DEGREES;
        state->target_angle_degrees = target_angle_degrees;
    }
    ServoControlUnlock();

    if (!start_requested && output_enabled) {
        /* 只关闭本路 CCP，不影响另一只仍在运行的舵机。 */
        if (!ServoStop(state->servo) || !ServoControlLock()) {
            ServoControlHandleFailure(device);
        } else {
            state->output_enabled = false;
            ServoControlUnlock();
        }
    } else if (start_requested && !output_enabled) {
        if (!ServoSetAngleDegrees(state->servo,
                current_angle_degrees) ||
            !ServoStart(state->servo) || !ServoControlLock()) {
            ServoControlHandleFailure(device);
        } else {
            state->output_enabled = true;
            ServoControlUnlock();
        }
    } else if (start_requested && output_enabled &&
               (current_angle_degrees != target_angle_degrees)) {
        uint16_t next_angle_degrees = ServoControlGetNextAngle(
            current_angle_degrees, target_angle_degrees);

        if (!ServoSetAngleDegrees(state->servo, next_angle_degrees) ||
            !ServoControlLock()) {
            ServoControlHandleFailure(device);
        } else {
            state->current_angle_degrees = next_angle_degrees;
            ServoControlUnlock();
        }
    }
}

/* 互斥量只保护 Application 状态；耗时的 PWM Module 调用均在锁外执行。 */
static bool ServoControlLock(void)
{
    return (servo_control_mutex != NULL) &&
           (xSemaphoreTake(servo_control_mutex,
                portMAX_DELAY) == pdPASS);
}

static void ServoControlUnlock(void)
{
    (void)xSemaphoreGive(servo_control_mutex);
}

/* 某一路硬件操作失败时只停止该路，另一只舵机继续执行自己的命令。 */
static void ServoControlHandleFailure(ServoControl_Device_e device)
{
    ServoControlDeviceState *state = &servo_control_devices[device];

    if (state->servo != NULL) {
        (void)ServoStop(state->servo);
    }
    if (ServoControlLock()) {
        state->start_requested = false;
        state->output_enabled  = false;
        state->faulted         = true;
        ServoControlUnlock();
    }
}

static void ServoControlStopAllRegistered(void)
{
    uint32_t index;

    for (index = 0U; index < SERVO_CONTROL_DEVICE_COUNT; ++index) {
        if (servo_control_devices[index].servo != NULL) {
            (void)ServoStop(servo_control_devices[index].servo);
        }
    }
}

/* 两路均可在 app_config.h 中独立关闭。 */
static bool ServoControlDeviceIsConfigured(ServoControl_Device_e device)
{
    if (device == SERVO_CONTROL_DEVICE_OUTPUT_0) {
        return APP_ENABLE_SERVO_CONTROL_OUTPUT_0 != 0U;
    }
    if (device == SERVO_CONTROL_DEVICE_OUTPUT_1) {
        return APP_ENABLE_SERVO_CONTROL_OUTPUT_1 != 0U;
    }
    return false;
}

static bool ServoControlDeviceStartsEnabled(ServoControl_Device_e device)
{
    return (device == SERVO_CONTROL_DEVICE_OUTPUT_0)
               ? (APP_SERVO_CONTROL_OUTPUT_0_START_ENABLED != 0U)
               : (APP_SERVO_CONTROL_OUTPUT_1_START_ENABLED != 0U);
}

static bool ServoControlDeviceAutoSweepEnabled(
    ServoControl_Device_e device)
{
    return (device == SERVO_CONTROL_DEVICE_OUTPUT_0)
               ? (APP_SERVO_CONTROL_OUTPUT_0_AUTO_SWEEP_ENABLED != 0U)
               : (APP_SERVO_CONTROL_OUTPUT_1_AUTO_SWEEP_ENABLED != 0U);
}

static Servo_Device_e ServoControlToServoDevice(
    ServoControl_Device_e device)
{
    return (device == SERVO_CONTROL_DEVICE_OUTPUT_1)
               ? SERVO_DEVICE_OUTPUT_1
               : SERVO_DEVICE_OUTPUT_0;
}

/* 按配置步长向目标角度移动，最后一步自动钳位到目标值。 */
static uint16_t ServoControlGetNextAngle(
    uint16_t current_angle_degrees, uint16_t target_angle_degrees)
{
    if (current_angle_degrees < target_angle_degrees) {
        uint16_t remaining_degrees =
            target_angle_degrees - current_angle_degrees;
        return (remaining_degrees <= APP_SERVO_CONTROL_STEP_DEGREES)
                   ? target_angle_degrees
                   : (uint16_t)(current_angle_degrees +
                         APP_SERVO_CONTROL_STEP_DEGREES);
    }

    {
        uint16_t remaining_degrees =
            current_angle_degrees - target_angle_degrees;
        return (remaining_degrees <= APP_SERVO_CONTROL_STEP_DEGREES)
                   ? target_angle_degrees
                   : (uint16_t)(current_angle_degrees -
                         APP_SERVO_CONTROL_STEP_DEGREES);
    }
}
#endif
