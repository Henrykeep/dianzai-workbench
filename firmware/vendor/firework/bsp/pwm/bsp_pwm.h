/**
 * @file bsp_pwm.h
 * @brief 共享定时器双通道 PWM 的配置、启停和安全关断接口。
 */
#ifndef BSP_PWM_H
#define BSP_PWM_H

#include <stdbool.h>
#include <stdint.h>

/** LP-MSPM0G3507 板级层向上提供的逻辑 PWM 通道。 */
typedef enum {
    /* TIMG7 CCP0，映射到 PA23。 */
    BSP_PWM_CHANNEL_OUTPUT_0 = 0,
    /* TIMG7 CCP1，映射到 PA24。 */
    BSP_PWM_CHANNEL_OUTPUT_1,
    /* 通道总数，同时作为枚举范围上限。 */
    BSP_PWM_CHANNEL_COUNT
} BSP_PWM_Channel_e;

/** PWM 不透明实例，具体定时器信息仅保留在 BSP 内部。 */
typedef struct BSPPWMInstance BSPPWMInstance;

/** 注册指定板级 PWM 通道；参数非法时返回 NULL。 */
BSPPWMInstance *BSPPWMRegister(BSP_PWM_Channel_e channel);

/** 设置 PWM 周期计数和比较计数，运行时通过影子寄存器同步更新。 */
bool BSPPWMConfigure(BSPPWMInstance *instance,
    uint32_t period_counts, uint32_t compare_counts);

/** 启动或停止 PWM 输出。 */
bool BSPPWMSetEnabled(BSPPWMInstance *instance, bool enabled);

/** 无锁停止共享定时器、断开全部 CCP 并清除通道状态，供 fault 路径调用。 */
void BSPPWMEnterSafeState(void);

/** 返回 PWM 定时器经过分频后的计数时钟频率。 */
uint32_t BSPPWMGetClockFrequency(const BSPPWMInstance *instance);

/** 返回当前板级 PWM 定时器支持的最大周期计数。 */
uint32_t BSPPWMGetMaximumPeriodCounts(const BSPPWMInstance *instance);

#endif
