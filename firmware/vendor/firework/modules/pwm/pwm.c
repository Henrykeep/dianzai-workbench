/*
 * PWM Module 将频率、占空比或脉宽换算为计数值，并以静态互斥锁保护共享定时器。
 */
#include "modules/pwm/pwm.h"

#include <stddef.h>

#include "FreeRTOS.h"
#include "semphr.h"

#include "bsp/pwm/bsp_pwm.h"

#define PWM_DUTY_CYCLE_MAXIMUM       (100U)
#define PWM_DUTY_CYCLE_SCALE         (10000U)
#define PWM_MICROSECONDS_PER_SECOND  (1000000UL)
#define PWM_MINIMUM_PERIOD_COUNTS    (2U)

struct PWMInstance {
    /* 应用可见的逻辑 PWM 编号。 */
    PWM_Device_e device;
    /* 真实定时器资源由 BSP 管理。 */
    BSPPWMInstance *pwm;
    /* 保存当前逻辑参数，修改其中一项时可重算完整硬件配置。 */
    uint32_t frequency_hz;
    uint32_t period_counts;
    uint16_t duty_cycle_basis_points;
    bool enabled;
    /* 防止多个任务同时修改周期和比较寄存器。 */
    SemaphoreHandle_t mutex;
    StaticSemaphore_t mutex_control;
    bool registered;
};

/* PWM 资源数量固定，使用静态实例池。 */
static PWMInstance pwm_instances[PWM_DEVICE_COUNT];
/* 两个逻辑通道共用 TIMG7，所有寄存器修改必须串行执行。 */
static SemaphoreHandle_t pwm_hardware_mutex;
static StaticSemaphore_t pwm_hardware_mutex_control;

static bool PWMIsValid(const PWMInstance *instance);
static bool PWMCalculateCounts(BSPPWMInstance *pwm, uint32_t frequency_hz,
    uint16_t duty_cycle_basis_points, uint32_t *period_counts,
    uint32_t *compare_counts);

/* 注册逻辑 PWM，计算初始计数值并按配置决定是否立即启动。 */
PWMInstance *PWMRegister(PWM_Device_e device, const PWMConfig *config)
{
    BSP_PWM_Channel_e channel;
    PWMInstance *instance;
    uint32_t period_counts;
    uint32_t compare_counts;

    if ((device < PWM_DEVICE_OUTPUT_0) || (device >= PWM_DEVICE_COUNT) ||
        (config == NULL) ||
        (config->duty_cycle_percent > PWM_DUTY_CYCLE_MAXIMUM)) {
        return NULL;
    }

    switch (device) {
        case PWM_DEVICE_OUTPUT_0:
            channel = BSP_PWM_CHANNEL_OUTPUT_0;
            break;

        case PWM_DEVICE_OUTPUT_1:
            channel = BSP_PWM_CHANNEL_OUTPUT_1;
            break;

        default:
            return NULL;
    }

    instance = &pwm_instances[device];
    if (instance->registered) {
        return instance;
    }

    instance->mutex = xSemaphoreCreateMutexStatic(&instance->mutex_control);
    if (instance->mutex == NULL) {
        return NULL;
    }

    if (pwm_hardware_mutex == NULL) {
        pwm_hardware_mutex = xSemaphoreCreateMutexStatic(
            &pwm_hardware_mutex_control);
    }
    if ((pwm_hardware_mutex == NULL) ||
        (xSemaphoreTake(pwm_hardware_mutex, portMAX_DELAY) != pdPASS)) {
        return NULL;
    }

    instance->pwm = BSPPWMRegister(channel);
    if ((instance->pwm == NULL) ||
        !PWMCalculateCounts(instance->pwm, config->frequency_hz,
            (uint16_t)config->duty_cycle_percent * 100U, &period_counts,
            &compare_counts) ||
        !BSPPWMConfigure(instance->pwm, period_counts, compare_counts)) {
        (void)xSemaphoreGive(pwm_hardware_mutex);
        return NULL;
    }
    (void)xSemaphoreGive(pwm_hardware_mutex);

    instance->device = device;
    instance->frequency_hz = config->frequency_hz;
    instance->period_counts = period_counts;
    instance->duty_cycle_basis_points =
        (uint16_t)config->duty_cycle_percent * 100U;
    instance->enabled    = false;
    instance->registered = true;

    if (config->start_enabled && !PWMStart(instance)) {
        instance->registered = false;
        return NULL;
    }

    return instance;
}

/* 线程安全地重算并更新 PWM 周期，同时保持当前占空比。 */
bool PWMSetFrequency(PWMInstance *instance, uint32_t frequency_hz)
{
    uint32_t period_counts;
    uint32_t compare_counts;
    bool result;

    if (!PWMIsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = PWMCalculateCounts(instance->pwm, frequency_hz,
                 instance->duty_cycle_basis_points, &period_counts,
                 &compare_counts) &&
             (xSemaphoreTake(pwm_hardware_mutex, portMAX_DELAY) == pdPASS);
    if (result) {
        result = BSPPWMConfigure(
            instance->pwm, period_counts, compare_counts);
        (void)xSemaphoreGive(pwm_hardware_mutex);
    }

    if (result) {
        instance->frequency_hz  = frequency_hz;
        instance->period_counts = period_counts;
    }

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 线程安全地修改 PWM 占空比，并保持当前频率不变。 */
bool PWMSetDutyCycle(PWMInstance *instance, uint8_t duty_cycle_percent)
{
    uint32_t period_counts;
    uint32_t compare_counts;
    bool result;

    if (!PWMIsValid(instance) ||
        (duty_cycle_percent > PWM_DUTY_CYCLE_MAXIMUM) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = PWMCalculateCounts(instance->pwm, instance->frequency_hz,
                 (uint16_t)duty_cycle_percent * 100U,
                 &period_counts, &compare_counts) &&
             (xSemaphoreTake(pwm_hardware_mutex, portMAX_DELAY) == pdPASS);
    if (result) {
        result = BSPPWMConfigure(
            instance->pwm, period_counts, compare_counts);
        (void)xSemaphoreGive(pwm_hardware_mutex);
    }

    if (result) {
        instance->period_counts = period_counts;
        instance->duty_cycle_basis_points =
            (uint16_t)duty_cycle_percent * 100U;
    }

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 将微秒脉宽按当前计数时钟换算为高电平计数，供舵机等精细脉宽控制使用。 */
bool PWMSetPulseWidthMicroseconds(
    PWMInstance *instance, uint32_t pulse_width_microseconds)
{
    uint32_t clock_frequency;
    uint32_t pulse_counts;
    uint32_t compare_counts;
    uint64_t scaled_pulse;
    uint64_t scaled_duty_cycle;
    bool result;

    if (!PWMIsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    clock_frequency = BSPPWMGetClockFrequency(instance->pwm);
    scaled_pulse = ((uint64_t)clock_frequency *
                       pulse_width_microseconds) +
                   (PWM_MICROSECONDS_PER_SECOND / 2U);
    if ((clock_frequency == 0U) ||
        ((scaled_pulse / PWM_MICROSECONDS_PER_SECOND) >
            instance->period_counts)) {
        (void)xSemaphoreGive(instance->mutex);
        return false;
    }

    pulse_counts = (uint32_t)(
        scaled_pulse / PWM_MICROSECONDS_PER_SECOND);
    compare_counts = instance->period_counts - pulse_counts;
    result = xSemaphoreTake(
                 pwm_hardware_mutex, portMAX_DELAY) == pdPASS;
    if (result) {
        result = BSPPWMConfigure(
            instance->pwm, instance->period_counts, compare_counts);
        (void)xSemaphoreGive(pwm_hardware_mutex);
    }
    if (result) {
        scaled_duty_cycle =
            ((uint64_t)pulse_counts * PWM_DUTY_CYCLE_SCALE) +
            (instance->period_counts / 2U);
        instance->duty_cycle_basis_points = (uint16_t)(
            scaled_duty_cycle / instance->period_counts);
    }

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 线程安全地启用对应 CCP 输出；共享定时器只需启动一次。 */
bool PWMStart(PWMInstance *instance)
{
    bool result;

    if (!PWMIsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = xSemaphoreTake(
                 pwm_hardware_mutex, portMAX_DELAY) == pdPASS;
    if (result) {
        result = BSPPWMSetEnabled(instance->pwm, true);
        (void)xSemaphoreGive(pwm_hardware_mutex);
    }
    if (result) {
        instance->enabled = true;
    }

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 线程安全地关闭对应 CCP；另一通道运行时保持共享定时器计数。 */
bool PWMStop(PWMInstance *instance)
{
    bool result;

    if (!PWMIsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = xSemaphoreTake(
                 pwm_hardware_mutex, portMAX_DELAY) == pdPASS;
    if (result) {
        result = BSPPWMSetEnabled(instance->pwm, false);
        (void)xSemaphoreGive(pwm_hardware_mutex);
    }
    if (result) {
        instance->enabled = false;
    }

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 将频率和百分比占空比换算为定时器周期与比较计数。 */
static bool PWMCalculateCounts(BSPPWMInstance *pwm, uint32_t frequency_hz,
    uint16_t duty_cycle_basis_points, uint32_t *period_counts,
    uint32_t *compare_counts)
{
    uint32_t clock_frequency;
    uint32_t maximum_period;
    uint32_t calculated_period;
    uint64_t scaled_compare;

    if ((pwm == NULL) || (frequency_hz == 0U) ||
        (duty_cycle_basis_points > PWM_DUTY_CYCLE_SCALE) ||
        (period_counts == NULL) || (compare_counts == NULL)) {
        return false;
    }

    clock_frequency = BSPPWMGetClockFrequency(pwm);
    maximum_period  = BSPPWMGetMaximumPeriodCounts(pwm);
    if ((clock_frequency == 0U) ||
        (frequency_hz > (clock_frequency / PWM_MINIMUM_PERIOD_COUNTS))) {
        return false;
    }

    calculated_period =
        (clock_frequency + (frequency_hz / 2U)) / frequency_hz;

    if ((calculated_period < PWM_MINIMUM_PERIOD_COUNTS) ||
        (calculated_period > maximum_period)) {
        return false;
    }

    scaled_compare = (uint64_t)calculated_period *
                     (PWM_DUTY_CYCLE_SCALE - duty_cycle_basis_points);
    *period_counts = calculated_period;
    *compare_counts =
        (uint32_t)((scaled_compare + (PWM_DUTY_CYCLE_SCALE / 2U)) /
                   PWM_DUTY_CYCLE_SCALE);
    return true;
}

/* 检查 PWM 模块实例及其互斥锁、板级句柄是否有效。 */
static bool PWMIsValid(const PWMInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->device >= PWM_DEVICE_OUTPUT_0) &&
           (instance->device < PWM_DEVICE_COUNT) &&
           (instance->pwm != NULL) && (instance->mutex != NULL);
}
