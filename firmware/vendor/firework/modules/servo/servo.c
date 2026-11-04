/*
 * Servo Module 在 PWM 之上完成角度到脉宽的换算，并保存线程安全的目标状态。
 */
#include "modules/servo/servo.h"

#include <stddef.h>

#include "FreeRTOS.h"
#include "semphr.h"

#include "modules/pwm/pwm.h"

#define SERVO_CONTROL_FREQUENCY_HZ (50UL)

struct ServoInstance {
    Servo_Device_e device;
    PWMInstance *pwm;
    uint16_t minimum_pulse_width_microseconds;
    uint16_t maximum_pulse_width_microseconds;
    uint16_t maximum_angle_degrees;
    uint16_t angle_degrees;
    uint16_t pulse_width_microseconds;
    bool enabled;
    SemaphoreHandle_t mutex;
    StaticSemaphore_t mutex_control;
    bool registered;
};

/* 舵机资源数量固定，使用静态实例池。 */
static ServoInstance servo_instances[SERVO_DEVICE_COUNT];

static bool ServoIsValid(const ServoInstance *instance);
static uint16_t ServoAngleToPulseWidth(
    const ServoInstance *instance, uint16_t angle_degrees);
static uint16_t ServoPulseWidthToAngle(
    const ServoInstance *instance, uint16_t pulse_width_microseconds);

/* 注册舵机并将可配置角度范围线性映射到 50 Hz PWM 脉宽。 */
ServoInstance *ServoRegister(
    Servo_Device_e device, const ServoConfig *config)
{
    static const PWMConfig pwm_config = {
        SERVO_CONTROL_FREQUENCY_HZ,
        0U,
        false
    };
    ServoInstance *instance;
    PWM_Device_e pwm_device;
    uint16_t initial_pulse_width;

    if ((device < SERVO_DEVICE_OUTPUT_0) ||
        (device >= SERVO_DEVICE_COUNT) || (config == NULL) ||
        (config->minimum_pulse_width_microseconds == 0U) ||
        (config->maximum_pulse_width_microseconds <=
            config->minimum_pulse_width_microseconds) ||
        (config->maximum_angle_degrees == 0U) ||
        (config->initial_angle_degrees >
            config->maximum_angle_degrees)) {
        return NULL;
    }

    switch (device) {
        case SERVO_DEVICE_OUTPUT_0:
            pwm_device = PWM_DEVICE_OUTPUT_0;
            break;

        case SERVO_DEVICE_OUTPUT_1:
            pwm_device = PWM_DEVICE_OUTPUT_1;
            break;

        default:
            return NULL;
    }

    instance = &servo_instances[device];
    if (instance->registered) {
        return instance;
    }

    instance->mutex = xSemaphoreCreateMutexStatic(
        &instance->mutex_control);
    if (instance->mutex == NULL) {
        return NULL;
    }

    instance->pwm = PWMRegister(pwm_device, &pwm_config);
    if (instance->pwm == NULL) {
        return NULL;
    }

    instance->device = device;
    instance->minimum_pulse_width_microseconds =
        config->minimum_pulse_width_microseconds;
    instance->maximum_pulse_width_microseconds =
        config->maximum_pulse_width_microseconds;
    instance->maximum_angle_degrees =
        config->maximum_angle_degrees;
    initial_pulse_width = ServoAngleToPulseWidth(
        instance, config->initial_angle_degrees);

    if (!PWMStop(instance->pwm) ||
        !PWMSetFrequency(instance->pwm,
            SERVO_CONTROL_FREQUENCY_HZ) ||
        !PWMSetPulseWidthMicroseconds(
            instance->pwm, initial_pulse_width) ||
        (config->start_enabled && !PWMStart(instance->pwm))) {
        instance->pwm = NULL;
        return NULL;
    }

    instance->angle_degrees = config->initial_angle_degrees;
    instance->pulse_width_microseconds = initial_pulse_width;
    instance->enabled    = config->start_enabled;
    instance->registered = true;
    return instance;
}

/* 将角度线性换算成脉宽，并通过 PWM Module 原子更新硬件。 */
bool ServoSetAngleDegrees(
    ServoInstance *instance, uint16_t angle_degrees)
{
    uint16_t pulse_width;
    bool result;

    if (!ServoIsValid(instance) ||
        (angle_degrees > instance->maximum_angle_degrees) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    pulse_width = ServoAngleToPulseWidth(instance, angle_degrees);
    result = PWMSetPulseWidthMicroseconds(instance->pwm, pulse_width);
    if (result) {
        instance->angle_degrees = angle_degrees;
        instance->pulse_width_microseconds = pulse_width;
    }

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 允许按舵机标定结果直接设置脉宽，并同步更新近似角度状态。 */
bool ServoSetPulseWidthMicroseconds(
    ServoInstance *instance, uint16_t pulse_width_microseconds)
{
    bool result;

    if (!ServoIsValid(instance) ||
        (pulse_width_microseconds <
            instance->minimum_pulse_width_microseconds) ||
        (pulse_width_microseconds >
            instance->maximum_pulse_width_microseconds) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = PWMSetPulseWidthMicroseconds(
        instance->pwm, pulse_width_microseconds);
    if (result) {
        instance->pulse_width_microseconds = pulse_width_microseconds;
        instance->angle_degrees = ServoPulseWidthToAngle(
            instance, pulse_width_microseconds);
    }

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 启动对应 PA23/PA24 引脚上的舵机控制脉冲。 */
bool ServoStart(ServoInstance *instance)
{
    bool result;

    if (!ServoIsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = PWMStart(instance->pwm);
    if (result) {
        instance->enabled = true;
    }

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 停止定时器输出，舵机将不再收到保持位置的控制脉冲。 */
bool ServoStop(ServoInstance *instance)
{
    bool result;

    if (!ServoIsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = PWMStop(instance->pwm);
    if (result) {
        instance->enabled = false;
    }

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

bool ServoGetAngleDegrees(
    ServoInstance *instance, uint16_t *angle_degrees)
{
    if (!ServoIsValid(instance) || (angle_degrees == NULL) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    *angle_degrees = instance->angle_degrees;
    (void)xSemaphoreGive(instance->mutex);
    return true;
}

bool ServoGetPulseWidthMicroseconds(
    ServoInstance *instance, uint16_t *pulse_width_microseconds)
{
    if (!ServoIsValid(instance) ||
        (pulse_width_microseconds == NULL) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    *pulse_width_microseconds =
        instance->pulse_width_microseconds;
    (void)xSemaphoreGive(instance->mutex);
    return true;
}

bool ServoIsEnabled(const ServoInstance *instance)
{
    return ServoIsValid(instance) && instance->enabled;
}

/* 使用 32 位中间值完成角度到脉宽的四舍五入线性映射。 */
static uint16_t ServoAngleToPulseWidth(
    const ServoInstance *instance, uint16_t angle_degrees)
{
    uint32_t pulse_range;
    uint32_t scaled_pulse;

    pulse_range = (uint32_t)instance->maximum_pulse_width_microseconds -
                  instance->minimum_pulse_width_microseconds;
    scaled_pulse = (pulse_range * angle_degrees) +
                   (instance->maximum_angle_degrees / 2U);
    return (uint16_t)(instance->minimum_pulse_width_microseconds +
        (scaled_pulse / instance->maximum_angle_degrees));
}

/* 将直接设置的脉宽反算为最接近的逻辑角度。 */
static uint16_t ServoPulseWidthToAngle(
    const ServoInstance *instance, uint16_t pulse_width_microseconds)
{
    uint32_t pulse_range;
    uint32_t pulse_offset;
    uint32_t scaled_angle;

    pulse_range = (uint32_t)instance->maximum_pulse_width_microseconds -
                  instance->minimum_pulse_width_microseconds;
    pulse_offset = (uint32_t)pulse_width_microseconds -
                   instance->minimum_pulse_width_microseconds;
    scaled_angle = (pulse_offset * instance->maximum_angle_degrees) +
                   (pulse_range / 2U);
    return (uint16_t)(scaled_angle / pulse_range);
}

static bool ServoIsValid(const ServoInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->device >= SERVO_DEVICE_OUTPUT_0) &&
           (instance->device < SERVO_DEVICE_COUNT) &&
           (instance->pwm != NULL) && (instance->mutex != NULL);
}
