/**
 * @file motor_dc.h
 * @brief 直流有刷电机驱动（H 桥：PWM + 方向）。只依赖 pal.h。
 *
 * 版本：MOTOR_DC_VERSION（与同目录 VERSION 文件一致）
 *
 * 支持两种常见接法：
 *  - MOTOR_DC_PWM_IN1_IN2：一路 PWM 调速 + 两路方向脚（TB6612 的 PWMA/AIN1/AIN2 等）
 *      正转 IN1=1,IN2=0；反转 IN1=0,IN2=1；刹车 IN1=IN2=1；滑行 IN1=IN2=0
 *  - MOTOR_DC_PWM_DIR：一路 PWM + 一路方向脚（很多集成驱动板）
 *      in2 填 PAL_ID_NONE；此模式没有独立刹车，stop(BRAKE) 等同占空比 0
 *  （双 PWM 接法如 DRV8833/L298N 的 IN1/IN2 都接 PWM，留作后续版本，见 README）
 *
 * 安全行为：
 *  - 换向时先把 PWM 置 0，再改方向脚，再给新占空比，避免换向瞬间大电流
 *  - 指令被限制在 [-max_duty, +max_duty]；NaN 指令视为 0
 */
#ifndef MOTOR_DC_H
#define MOTOR_DC_H

#include <stdbool.h>
#include "pal.h"

#define MOTOR_DC_VERSION "1.0.0"

typedef enum {
    MOTOR_DC_PWM_IN1_IN2 = 0,
    MOTOR_DC_PWM_DIR     = 1
} motor_dc_mode_t;

typedef enum {
    MOTOR_DC_COAST = 0, /**< 滑行：断开驱动 */
    MOTOR_DC_BRAKE = 1  /**< 刹车：短接绕组（仅 IN1_IN2 模式） */
} motor_dc_stop_t;

typedef struct {
    motor_dc_mode_t mode;
    pal_id_t pwm;       /**< PWM 逻辑 ID，例如 RES_PWM_MOTOR_A */
    pal_id_t in1;       /**< 方向脚 1（DIR 模式下即方向脚） */
    pal_id_t in2;       /**< 方向脚 2；DIR 模式填 PAL_ID_NONE */
    bool     invert;    /**< 电机装反了就置 true，不要去改接线或代码 */
    float    deadband;  /**< 死区补偿 0..0.5：非零指令映射到 [deadband, max_duty] */
    float    max_duty;  /**< 最大占空比 0..1，限制最大电流/速度 */
} motor_dc_cfg_t;

typedef struct {
    motor_dc_cfg_t cfg;
    float cmd;          /**< 最近一次指令（-1..1，已限幅） */
    int8_t dir;         /**< 当前方向：1 / -1 / 0 */
    bool ready;
} motor_dc_t;

/** 默认配置：IN1_IN2 模式，不反向，无死区，max_duty=1。ID 需调用者填写。 */
motor_dc_cfg_t motor_dc_cfg_default(void);

/** 校验配置并把电机置于滑行状态。 */
dz_err_t motor_dc_init(motor_dc_t *m, const motor_dc_cfg_t *cfg);

/** 设置指令 -1..1（正值=正转）。超出范围被限幅，不报错。[ISR-safe] */
dz_err_t motor_dc_set(motor_dc_t *m, float cmd);

/** 停止。[ISR-safe] */
dz_err_t motor_dc_stop(motor_dc_t *m, motor_dc_stop_t how);

float motor_dc_get_cmd(const motor_dc_t *m);

/**
 * 驱动自检（会让电机短暂转动！先把机构架空或确保安全）：
 *  依次以 test_duty 正转、反转各 hold_ms 毫秒，然后滑行停止，期间检查每次
 *  PAL 调用返回值。电机转向是否正确需要配合编码器判断，见 apps 中的方向自检。
 */
dz_err_t motor_dc_selftest(motor_dc_t *m, float test_duty, uint32_t hold_ms);

#endif /* MOTOR_DC_H */
