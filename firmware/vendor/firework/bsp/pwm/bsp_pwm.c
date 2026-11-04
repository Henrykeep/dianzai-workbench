/* PWM BSP 协调共享同一定时器周期的两个 CCP 通道，并统一控制安全启停。 */
#include "bsp/pwm/bsp_pwm.h"

#include <stddef.h>

#include "ti_msp_dl_config.h"

#define BSP_PWM_MINIMUM_PERIOD_COUNTS (2U)
#define BSP_PWM_MAXIMUM_PERIOD_COUNTS (UINT16_MAX)

struct BSPPWMInstance {
    /* 板级逻辑通道，由 BSP 解析到真实定时器及比较通道。 */
    BSP_PWM_Channel_e channel;
    GPTIMER_Regs *regs;
    DL_TIMER_CC_INDEX compare_index;
    /* setCCPDirection 会覆盖整个方向寄存器，因此保存本通道输出位。 */
    uint32_t output_direction;
    /* 两路共用周期；记录本通道最近一次配置，用于阻止陈旧配置启动。 */
    uint32_t configured_period_counts;
    /* 记录输出状态，决定配置写入活动寄存器还是影子寄存器。 */
    bool enabled;
    bool registered;
};

/* PWM 资源固定，使用静态实例池避免动态内存分配。 */
static BSPPWMInstance pwm_instances[BSP_PWM_CHANNEL_COUNT];
static uint32_t pwm_period_counts;

static bool BSPPWMIsValid(const BSPPWMInstance *instance);
static bool BSPPWMAnyChannelEnabled(void);
static bool BSPPWMAnyOtherChannelEnabled(const BSPPWMInstance *instance);
static void BSPPWMApplyDirections(void);

/* 注册逻辑 PWM 通道，并保证定时器初始处于停止状态。 */
BSPPWMInstance *BSPPWMRegister(BSP_PWM_Channel_e channel)
{
    BSPPWMInstance *instance;

    if ((channel < BSP_PWM_CHANNEL_OUTPUT_0) ||
        (channel >= BSP_PWM_CHANNEL_COUNT)) {
        return NULL;
    }

    instance = &pwm_instances[channel];
    if (instance->registered) {
        return instance;
    }

    switch (channel) {
        case BSP_PWM_CHANNEL_OUTPUT_0:
            instance->regs          = PWM_OUTPUT_INST;
            instance->compare_index = GPIO_PWM_OUTPUT_C0_IDX;
            instance->output_direction = DL_TIMER_CC0_OUTPUT;
            break;

        case BSP_PWM_CHANNEL_OUTPUT_1:
            instance->regs          = PWM_OUTPUT_INST;
            instance->compare_index = GPIO_PWM_OUTPUT_C1_IDX;
            instance->output_direction = DL_TIMER_CC1_OUTPUT;
            break;

        default:
            return NULL;
    }

    instance->channel    = channel;
    instance->enabled    = false;
    instance->configured_period_counts = 0U;
    instance->registered = true;

    if (!BSPPWMAnyChannelEnabled()) {
        DL_TimerG_stopCounter(instance->regs);
    }
    BSPPWMApplyDirections();
    return instance;
}

/* 更新 PWM 周期和比较值，停止状态下直接写入活动寄存器。 */
bool BSPPWMConfigure(BSPPWMInstance *instance,
    uint32_t period_counts, uint32_t compare_counts)
{
    bool timer_running;

    if (!BSPPWMIsValid(instance) ||
        (period_counts < BSP_PWM_MINIMUM_PERIOD_COUNTS) ||
        (period_counts > BSP_PWM_MAXIMUM_PERIOD_COUNTS) ||
        (compare_counts > period_counts)) {
        return false;
    }

    /* 另一通道运行时周期不能改变，但本通道的比较值仍可独立更新。 */
    if (BSPPWMAnyOtherChannelEnabled(instance) &&
        (pwm_period_counts != period_counts)) {
        return false;
    }

    timer_running = BSPPWMAnyChannelEnabled();
    if (!timer_running) {
        /* 定时器未运行时直接更新，确保首次启动即使用新参数。 */
        DL_Timer_disableShadowFeatures(instance->regs);
    }

    DL_TimerG_setLoadValue(instance->regs, period_counts);
    DL_TimerG_setCaptureCompareValue(
        instance->regs, compare_counts, instance->compare_index);

    if (!timer_running) {
        DL_TimerG_setTimerCount(instance->regs, period_counts);
        DL_TimerG_enableShadowFeatures(instance->regs);
    }

    pwm_period_counts = period_counts;
    instance->configured_period_counts = period_counts;
    return true;
}

/* 单独启停一个 CCP；只有最后一路关闭时才停止共享定时器。 */
bool BSPPWMSetEnabled(BSPPWMInstance *instance, bool enabled)
{
    if (!BSPPWMIsValid(instance)) {
        return false;
    }

    if (enabled == instance->enabled) {
        return true;
    }

    if (enabled) {
        if ((instance->configured_period_counts == 0U) ||
            (instance->configured_period_counts != pwm_period_counts)) {
            return false;
        }

        if (!BSPPWMAnyChannelEnabled()) {
            DL_TimerG_setTimerCount(
                instance->regs, DL_TimerG_getLoadValue(instance->regs));
            DL_TimerG_startCounter(instance->regs);
        }
        instance->enabled = true;
        BSPPWMApplyDirections();
    } else {
        instance->enabled = false;
        BSPPWMApplyDirections();
        if (!BSPPWMAnyChannelEnabled()) {
            DL_TimerG_stopCounter(instance->regs);
        }
    }

    return true;
}

/* fault 路径不能获取 Module 互斥锁，直接关闭硬件并同步清除两路 BSP 状态。 */
void BSPPWMEnterSafeState(void)
{
    uint32_t index;

    DL_TimerG_stopCounter(PWM_OUTPUT_INST);
    DL_TimerG_setCCPDirection(
        PWM_OUTPUT_INST, DL_TIMER_CC0_INPUT | DL_TIMER_CC1_INPUT);
    for (index = 0U; index < BSP_PWM_CHANNEL_COUNT; ++index) {
        pwm_instances[index].enabled = false;
    }
}

/* 返回 SysConfig 生成的 PWM 计数时钟频率。 */
uint32_t BSPPWMGetClockFrequency(const BSPPWMInstance *instance)
{
    return BSPPWMIsValid(instance) ? PWM_OUTPUT_INST_CLK_FREQ : 0U;
}

/* 返回 TIMG7 的 16 位周期计数上限。 */
uint32_t BSPPWMGetMaximumPeriodCounts(const BSPPWMInstance *instance)
{
    return BSPPWMIsValid(instance) ? BSP_PWM_MAXIMUM_PERIOD_COUNTS : 0U;
}

/* 检查 PWM 实例是否已经完成注册且硬件映射有效。 */
static bool BSPPWMIsValid(const BSPPWMInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->channel >= BSP_PWM_CHANNEL_OUTPUT_0) &&
           (instance->channel < BSP_PWM_CHANNEL_COUNT) &&
           (instance->regs != NULL);
}

/* 检查共享 TIMG7 是否至少有一个 CCP 正在输出。 */
static bool BSPPWMAnyChannelEnabled(void)
{
    uint32_t index;

    for (index = 0U; index < BSP_PWM_CHANNEL_COUNT; ++index) {
        if (pwm_instances[index].registered &&
            pwm_instances[index].enabled) {
            return true;
        }
    }
    return false;
}

/* 改变共享周期前，确认不会干扰另一路正在运行的 PWM。 */
static bool BSPPWMAnyOtherChannelEnabled(const BSPPWMInstance *instance)
{
    uint32_t index;

    for (index = 0U; index < BSP_PWM_CHANNEL_COUNT; ++index) {
        if ((&pwm_instances[index] != instance) &&
            pwm_instances[index].registered &&
            pwm_instances[index].enabled) {
            return true;
        }
    }
    return false;
}

/* 一次写入两路 CCP 方向，避免配置一路时意外清除另一路输出位。 */
static void BSPPWMApplyDirections(void)
{
    uint32_t direction = 0U;
    uint32_t index;

    for (index = 0U; index < BSP_PWM_CHANNEL_COUNT; ++index) {
        if (pwm_instances[index].registered &&
            pwm_instances[index].enabled) {
            direction |= pwm_instances[index].output_direction;
        }
    }
    DL_TimerG_setCCPDirection(PWM_OUTPUT_INST, direction);
}
