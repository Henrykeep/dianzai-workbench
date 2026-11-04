/*
 * TB6612 BSP 管理双路方向 GPIO、共享 PWM 定时器和 STBY 功率级安全时序。
 */
#include "bsp/tb6612/bsp_tb6612.h"

#include <stddef.h>

#include "application/app_config.h"

#if APP_ENABLE_TB6612_CONTROL != 0U

#include "ti_msp_dl_config.h"

#define BSP_TB6612_MINIMUM_PERIOD_COUNTS (2U)
#define BSP_TB6612_MAXIMUM_PERIOD_COUNTS (UINT16_MAX)
#define BSP_TB6612_DUTY_SCALE            (100U)
#define BSP_TB6612_PWM_DIRECTION_MASK \
    (DL_TIMER_CC0_OUTPUT | DL_TIMER_CC1_OUTPUT)
#define BSP_TB6612_DIRECTION_PIN_MASK                         \
    (GPIO_TB6612_AIN1_PIN | GPIO_TB6612_AIN2_PIN |          \
        GPIO_TB6612_BIN1_PIN | GPIO_TB6612_BIN2_PIN)

struct BSPTB6612Instance {
    /* 两路电机共享的 PWM 周期计数。 */
    uint32_t period_counts;
    /* 记录功率级是否已通过 STBY 释放。 */
    bool standby_released;
    /* 静态实例只有注册后才允许被公开接口使用。 */
    bool registered;
};

/* 板上仅有一颗 TB6612，使用单一静态实例。 */
static BSPTB6612Instance tb6612_instance;

static bool BSPTB6612IsValid(const BSPTB6612Instance *instance);
static bool BSPTB6612ResolveMotor(BSP_TB6612_Motor_e motor,
    uint32_t *input_1_pin, uint32_t *input_2_pin,
    DL_TIMER_CC_INDEX *compare_index);

BSPTB6612Instance *BSPTB6612Register(void)
{
    if (tb6612_instance.registered) {
        return &tb6612_instance;
    }

    /* 注册前先硬件关断，避免继承复位前的方向和 PWM 状态。 */
    BSPTB6612EnterSafeState();
    tb6612_instance.period_counts = 0U;
    tb6612_instance.standby_released = false;
    tb6612_instance.registered = true;
    return &tb6612_instance;
}

bool BSPTB6612ConfigurePWM(
    BSPTB6612Instance *instance, uint32_t frequency_hz)
{
    uint32_t period_counts;

    if (!BSPTB6612IsValid(instance) || instance->standby_released ||
        (frequency_hz == 0U) ||
        (frequency_hz >
            (TB6612_PWM_INST_CLK_FREQ /
                BSP_TB6612_MINIMUM_PERIOD_COUNTS))) {
        return false;
    }

    /* 四舍五入换算定时器周期，并限制在 16 位装载寄存器范围内。 */
    period_counts =
        (TB6612_PWM_INST_CLK_FREQ + (frequency_hz / 2U)) /
        frequency_hz;
    if ((period_counts < BSP_TB6612_MINIMUM_PERIOD_COUNTS) ||
        (period_counts > BSP_TB6612_MAXIMUM_PERIOD_COUNTS)) {
        return false;
    }

    DL_TimerA_disableShadowFeatures(TB6612_PWM_INST);
    DL_TimerA_setLoadValue(TB6612_PWM_INST, period_counts);
    DL_TimerA_setCaptureCompareValue(TB6612_PWM_INST,
        period_counts, GPIO_TB6612_PWM_C0_IDX);
    DL_TimerA_setCaptureCompareValue(TB6612_PWM_INST,
        period_counts, GPIO_TB6612_PWM_C1_IDX);
    DL_TimerA_setTimerCount(TB6612_PWM_INST, period_counts);
    DL_TimerA_enableShadowFeatures(TB6612_PWM_INST);

    instance->period_counts = period_counts;
    return true;
}

bool BSPTB6612SetMotorOutput(BSPTB6612Instance *instance,
    BSP_TB6612_Motor_e motor, bool input_1_high,
    bool input_2_high, uint8_t duty_cycle_percent)
{
    uint32_t input_1_pin;
    uint32_t input_2_pin;
    uint32_t high_counts;
    uint32_t compare_counts;
    DL_TIMER_CC_INDEX compare_index;

    if (!BSPTB6612IsValid(instance) ||
        (instance->period_counts == 0U) ||
        (duty_cycle_percent > BSP_TB6612_DUTY_SCALE) ||
        !BSPTB6612ResolveMotor(
            motor, &input_1_pin, &input_2_pin, &compare_index)) {
        return false;
    }

    /* 先写方向，再更新 PWM，避免反向时短暂输出错误方向。 */
    if (input_1_high) {
        DL_GPIO_setPins(GPIO_TB6612_PORT, input_1_pin);
    } else {
        DL_GPIO_clearPins(GPIO_TB6612_PORT, input_1_pin);
    }
    if (input_2_high) {
        DL_GPIO_setPins(GPIO_TB6612_PORT, input_2_pin);
    } else {
        DL_GPIO_clearPins(GPIO_TB6612_PORT, input_2_pin);
    }

    /* 下数 PWM 的比较值等于周期减去高电平计数。 */
    high_counts = (uint32_t)((
        ((uint64_t)instance->period_counts * duty_cycle_percent) +
        (BSP_TB6612_DUTY_SCALE / 2U)) /
        BSP_TB6612_DUTY_SCALE);
    compare_counts = instance->period_counts - high_counts;
    DL_TimerA_setCaptureCompareValue(
        TB6612_PWM_INST, compare_counts, compare_index);
    return true;
}

bool BSPTB6612SetStandby(
    BSPTB6612Instance *instance, bool standby_released)
{
    if (!BSPTB6612IsValid(instance) ||
        (standby_released && (instance->period_counts == 0U))) {
        return false;
    }

    if (standby_released == instance->standby_released) {
        return true;
    }

    /* 释放时先稳定 MCU 输出，关闭时先切断功率级，避免产生瞬时驱动。 */
    if (standby_released) {
        DL_TimerA_setTimerCount(
            TB6612_PWM_INST, instance->period_counts);
        DL_TimerA_setCCPDirection(
            TB6612_PWM_INST, BSP_TB6612_PWM_DIRECTION_MASK);
        DL_TimerA_startCounter(TB6612_PWM_INST);
        /* PWM 和方向稳定后最后释放 STBY。 */
        DL_GPIO_setPins(GPIO_TB6612_PORT, GPIO_TB6612_STBY_PIN);
    } else {
        /* 首先关闭功率级，再停止 MCU 输出。 */
        DL_GPIO_clearPins(GPIO_TB6612_PORT, GPIO_TB6612_STBY_PIN);
        DL_TimerA_stopCounter(TB6612_PWM_INST);
        DL_TimerA_setCCPDirection(TB6612_PWM_INST,
            DL_TIMER_CC0_INPUT | DL_TIMER_CC1_INPUT);
    }

    instance->standby_released = standby_released;
    return true;
}

void BSPTB6612EnterSafeState(void)
{
    /* 该无锁路径可由初始化失败和 Fault 安全关断重复调用。 */
    DL_GPIO_clearPins(GPIO_TB6612_PORT, GPIO_TB6612_STBY_PIN);
    DL_TimerA_stopCounter(TB6612_PWM_INST);
    DL_TimerA_setCCPDirection(TB6612_PWM_INST,
        DL_TIMER_CC0_INPUT | DL_TIMER_CC1_INPUT);
    DL_GPIO_clearPins(
        GPIO_TB6612_PORT, BSP_TB6612_DIRECTION_PIN_MASK);
    tb6612_instance.standby_released = false;
}

static bool BSPTB6612IsValid(const BSPTB6612Instance *instance)
{
    return (instance == &tb6612_instance) && instance->registered;
}

static bool BSPTB6612ResolveMotor(BSP_TB6612_Motor_e motor,
    uint32_t *input_1_pin, uint32_t *input_2_pin,
    DL_TIMER_CC_INDEX *compare_index)
{
    if ((input_1_pin == NULL) || (input_2_pin == NULL) ||
        (compare_index == NULL)) {
        return false;
    }

    /* 将逻辑电机号解析为成对方向脚和各自的比较通道。 */
    switch (motor) {
        case BSP_TB6612_MOTOR_A:
            *input_1_pin = GPIO_TB6612_AIN1_PIN;
            *input_2_pin = GPIO_TB6612_AIN2_PIN;
            *compare_index = GPIO_TB6612_PWM_C0_IDX;
            return true;

        case BSP_TB6612_MOTOR_B:
            *input_1_pin = GPIO_TB6612_BIN1_PIN;
            *input_2_pin = GPIO_TB6612_BIN2_PIN;
            *compare_index = GPIO_TB6612_PWM_C1_IDX;
            return true;

        default:
            return false;
    }
}

#endif
