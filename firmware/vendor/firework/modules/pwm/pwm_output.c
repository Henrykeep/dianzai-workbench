/* PWMOutput 为菜单等单通道调用方提供 PA23 默认 PWM 的便捷封装。 */
#include "modules/pwm/pwm_output.h"

#include <stddef.h>

#include "modules/pwm/pwm.h"

#define PWM_OUTPUT_DEFAULT_FREQUENCY_HZ      (1000UL)
#define PWM_OUTPUT_DEFAULT_DUTY_CYCLE_PERCENT (50U)

/* 保存当前通用 PWM Output Module 实例。 */
static PWMInstance *pwm_output;

/* 注册默认 1 kHz、50% 参数；初始化完成后保持 PA23 输出关闭。 */
bool PWMOutputInit(void)
{
    static const PWMConfig config = {
        PWM_OUTPUT_DEFAULT_FREQUENCY_HZ,
        PWM_OUTPUT_DEFAULT_DUTY_CYCLE_PERCENT,
        false
    };

    if (pwm_output != NULL) {
        return true;
    }

    pwm_output = PWMRegister(PWM_DEVICE_OUTPUT_0, &config);
    return pwm_output != NULL;
}

/* 检查模块实例后修改 PWM 输出频率。 */
bool PWMOutputSetFrequency(uint32_t frequency_hz)
{
    return (pwm_output != NULL) &&
           PWMSetFrequency(pwm_output, frequency_hz);
}

/* 检查模块实例后修改 PWM 输出占空比。 */
bool PWMOutputSetDutyCycle(uint8_t duty_cycle_percent)
{
    return (pwm_output != NULL) &&
           PWMSetDutyCycle(pwm_output, duty_cycle_percent);
}

/* 检查模块实例后启动 PWM 输出。 */
bool PWMOutputStart(void)
{
    return (pwm_output != NULL) && PWMStart(pwm_output);
}

/* 检查模块实例后停止 PWM 输出。 */
bool PWMOutputStop(void)
{
    return (pwm_output != NULL) && PWMStop(pwm_output);
}
