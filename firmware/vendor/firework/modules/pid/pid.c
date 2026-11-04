/*
 * PID Module 提供固定实例池的位置式 PID、两种微分来源、限幅和条件积分抗饱和。
 */
#include "modules/pid/pid.h"

#include <float.h>
#include <stddef.h>

#define PID_INSTANCE_COUNT (4U)

struct PIDInstance {
    /* 配置和运行历史均由单一调用任务拥有，不在内部创建锁。 */
    PIDConfig config;
    float integral;
    float previous_error;
    float previous_measurement;
    float last_output;
    bool history_initialized;
    bool output_available;
    bool registered;
};

/* 固定实例池允许多个独立控制环同时使用 PID。 */
static PIDInstance pid_instances[PID_INSTANCE_COUNT];

static bool PIDIsValid(const PIDInstance *instance);
static bool PIDConfigIsValid(const PIDConfig *config);
static bool PIDValueIsFinite(float value);
static float PIDClamp(float value, float minimum, float maximum);
static void PIDClearState(PIDInstance *instance);

/* 从静态实例池注册控制器，并保存经过检查的初始配置。 */
PIDInstance *PIDRegister(const PIDConfig *config)
{
    size_t index;

    if (!PIDConfigIsValid(config)) {
        return NULL;
    }

    for (index = 0U; index < PID_INSTANCE_COUNT; ++index) {
        PIDInstance *instance = &pid_instances[index];

        if (!instance->registered) {
            instance->config     = *config;
            instance->registered = true;
            PIDClearState(instance);
            return instance;
        }
    }

    return NULL;
}

/* 修改 PID 参数，并清除旧参数对应的积分和微分历史。 */
bool PIDConfigure(PIDInstance *instance, const PIDConfig *config)
{
    if (!PIDIsValid(instance) || !PIDConfigIsValid(config)) {
        return false;
    }

    instance->config = *config;
    PIDClearState(instance);
    return true;
}

/* 保留参数，只清除运行期状态。 */
bool PIDReset(PIDInstance *instance)
{
    if (!PIDIsValid(instance)) {
        return false;
    }

    PIDClearState(instance);
    return true;
}

/* 计算位置式 PID，并执行积分限幅、输出限幅和条件积分抗饱和。 */
bool PIDProcess(PIDInstance *instance, float setpoint, float measurement,
    float delta_time_seconds, float *output)
{
    const PIDConfig *config;
    float error;
    float proportional;
    float integral_candidate;
    float derivative = 0.0F;
    float unclamped_output;
    float clamped_output;

    if (!PIDIsValid(instance) || (output == NULL) ||
        !PIDValueIsFinite(setpoint) || !PIDValueIsFinite(measurement) ||
        !PIDValueIsFinite(delta_time_seconds) ||
        (delta_time_seconds <= 0.0F)) {
        return false;
    }

    config = &instance->config;
    error  = setpoint - measurement;
    if (!PIDValueIsFinite(error)) {
        return false;
    }

    /* 积分候选先限幅，确认不会加重输出饱和后才提交到实例状态。 */
    proportional = config->kp * error;
    integral_candidate = PIDClamp(
        instance->integral + (config->ki * error * delta_time_seconds),
        config->integral_minimum, config->integral_maximum);

    if (instance->history_initialized) {
        if (config->derivative_mode == PID_DERIVATIVE_ON_MEASUREMENT) {
            derivative = -config->kd *
                         (measurement - instance->previous_measurement) /
                         delta_time_seconds;
        } else {
            derivative = config->kd *
                         (error - instance->previous_error) /
                         delta_time_seconds;
        }
    }

    unclamped_output = proportional + integral_candidate + derivative;
    if (!PIDValueIsFinite(proportional) ||
        !PIDValueIsFinite(integral_candidate) ||
        !PIDValueIsFinite(derivative) ||
        !PIDValueIsFinite(unclamped_output)) {
        return false;
    }

    clamped_output = PIDClamp(unclamped_output,
        config->output_minimum, config->output_maximum);

    /*
     * 输出已经饱和且新积分会让饱和更严重时，放弃本周期积分；
     * 当误差方向反转并推动输出离开饱和区时，仍允许积分回退。
     */
    if (((unclamped_output > config->output_maximum) &&
            (integral_candidate > instance->integral)) ||
        ((unclamped_output < config->output_minimum) &&
            (integral_candidate < instance->integral))) {
        integral_candidate = instance->integral;
        unclamped_output = proportional + integral_candidate + derivative;
        if (!PIDValueIsFinite(unclamped_output)) {
            return false;
        }
        clamped_output = PIDClamp(unclamped_output,
            config->output_minimum, config->output_maximum);
    }

    instance->integral             = integral_candidate;
    instance->previous_error       = error;
    instance->previous_measurement = measurement;
    instance->last_output          = clamped_output;
    instance->history_initialized  = true;
    instance->output_available     = true;
    *output                        = clamped_output;
    return true;
}

/* 返回控制器保存的最近一次成功输出。 */
bool PIDGetLastOutput(const PIDInstance *instance, float *output)
{
    if (!PIDIsValid(instance) || (output == NULL) ||
        !instance->output_available) {
        return false;
    }

    *output = instance->last_output;
    return true;
}

/* 检查实例是否已经注册且其配置仍然有效。 */
static bool PIDIsValid(const PIDInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           PIDConfigIsValid(&instance->config);
}

/* 检查所有参数为有限值、限幅关系正确且微分模式有效。 */
static bool PIDConfigIsValid(const PIDConfig *config)
{
    return (config != NULL) && PIDValueIsFinite(config->kp) &&
           PIDValueIsFinite(config->ki) &&
           PIDValueIsFinite(config->kd) &&
           PIDValueIsFinite(config->output_minimum) &&
           PIDValueIsFinite(config->output_maximum) &&
           PIDValueIsFinite(config->integral_minimum) &&
           PIDValueIsFinite(config->integral_maximum) &&
           (config->output_minimum < config->output_maximum) &&
           (config->integral_minimum <= config->integral_maximum) &&
           ((config->derivative_mode == PID_DERIVATIVE_ON_ERROR) ||
            (config->derivative_mode ==
                PID_DERIVATIVE_ON_MEASUREMENT));
}

/* 不依赖 libm 检查 NaN 和正负无穷。 */
static bool PIDValueIsFinite(float value)
{
    return (value == value) && (value <= FLT_MAX) &&
           (value >= -FLT_MAX);
}

/* 将浮点数限制在闭区间内。 */
static float PIDClamp(float value, float minimum, float maximum)
{
    if (value < minimum) {
        return minimum;
    }
    if (value > maximum) {
        return maximum;
    }
    return value;
}

/* 统一清空积分、历史输入和最近输出状态。 */
static void PIDClearState(PIDInstance *instance)
{
    instance->integral             = 0.0F;
    instance->previous_error       = 0.0F;
    instance->previous_measurement = 0.0F;
    instance->last_output          = 0.0F;
    instance->history_initialized  = false;
    instance->output_available     = false;
}
