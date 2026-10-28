/**
 * @file motor_2pwm.h
 * @brief 双 PWM 输入的 H 桥（DRV8833、L298N 的 IN1/IN2 都接 PWM、AT8236、TB67H450 等）。只依赖 pal.h。
 *
 * 与 motor_dc（TB6612：PWM + 两个方向脚）互补；没有改 motor_dc 的枚举，避免接口 MAJOR 变更（见 QUESTIONS 36）。
 * DRV8833 真值表（TI SLVSAR1E 表 2/3）：
 *   快衰减（滑行式）：正转 IN1=PWM、IN2=0；反转 IN1=0、IN2=PWM
 *   慢衰减（刹车式）：正转 IN1=1、IN2=PWM̅（占空 1−d）；反转 IN1=PWM̅、IN2=1
 *   滑行 IN1=IN2=0；刹车 IN1=IN2=1
 * 慢衰减时转速对占空比更线性、低速力矩更好，适合闭环调速；快衰减电流纹波小一些。
 * 两路 PWM 必须同频（board.yaml 放同一个定时器的两个通道）。
 * 版本：MOTOR_2PWM_VERSION
 */
#ifndef MOTOR_2PWM_H
#define MOTOR_2PWM_H
#include <stdbool.h>
#include "dz_err.h"
#include "pal.h"
#define MOTOR_2PWM_VERSION "1.0.0"

typedef enum { MOTOR_2PWM_FAST_DECAY = 0, MOTOR_2PWM_SLOW_DECAY = 1 } motor_2pwm_decay_t;

typedef struct {
    pal_id_t in1, in2;        /**< 两个 pwm 资源 */
    motor_2pwm_decay_t decay;
    bool  invert;
    float deadband;           /**< 0..0.5 */
    float max_duty;           /**< 0..1 */
} motor_2pwm_cfg_t;

typedef struct {
    motor_2pwm_cfg_t cfg;
    float cmd;
    bool ready;
} motor_2pwm_t;

motor_2pwm_cfg_t motor_2pwm_cfg_default(pal_id_t in1, pal_id_t in2);
dz_err_t motor_2pwm_init(motor_2pwm_t *m, const motor_2pwm_cfg_t *cfg);
/** -1..1，NaN 视为 0，超出限幅。[ISR-safe] */
dz_err_t motor_2pwm_set(motor_2pwm_t *m, float cmd);
/** brake=true 两脚全高（短接刹车），false 全低（滑行）。[ISR-safe] */
dz_err_t motor_2pwm_stop(motor_2pwm_t *m, bool brake);
/** 计算两路占空（纯函数，0..PAL_DUTY_MAX）。 */
void motor_2pwm_duties(const motor_2pwm_cfg_t *c, float cmd, uint16_t *d1, uint16_t *d2);
dz_err_t motor_2pwm_selftest(void);
#endif
