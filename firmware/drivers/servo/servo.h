/**
 * @file servo.h
 * @brief 舵机 PWM（50 Hz，脉宽微秒）。角度→脉宽映射 + 中位微调 + 反向 + 限位 + 速率限制。只依赖 pal.h。
 *
 * 映射：pulse = center_us + trim_us + angle/half_range_deg * (max_us-min_us)/2，再夹在 [min_us,max_us]。
 * 速率限制 slew_dps>0 时，servo_tick(dt) 让实际角度以不超过 slew_dps 的速度逼近目标。
 * 版本：SERVO_VERSION
 */
#ifndef SERVO_H
#define SERVO_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "pal.h"
#define SERVO_VERSION "1.0.0"

typedef struct {
    pal_id_t pwm;          /**< board.yaml pwm 资源（freq_hz: 50），如 RES_PWM_SERVO_X */
    uint16_t min_us;       /**< 典型 500（SG90/MG996R 约 500..2500） */
    uint16_t max_us;       /**< 典型 2500 */
    uint16_t center_us;    /**< 典型 1500 */
    int16_t  trim_us;      /**< 装配中位微调，±200 内 */
    float    half_range_deg; /**< 半行程角度，180° 舵机填 90 */
    float    lim_lo_deg, lim_hi_deg; /**< 软件限位（机构干涉保护） */
    float    slew_dps;     /**< 0 = 不限速 */
    bool     invert;
} servo_cfg_t;

typedef struct {
    servo_cfg_t cfg;
    float target, angle;
    uint16_t pulse_us;
    bool ready;
} servo_t;

servo_cfg_t servo_cfg_default(pal_id_t pwm);
dz_err_t servo_init(servo_t *s, const servo_cfg_t *cfg);
/** 设目标角度（度，超出限位被夹住）。slew_dps=0 时立即输出。NaN → DZ_EINVAL。 */
dz_err_t servo_set_deg(servo_t *s, float deg);
/** 直接给脉宽（标定用，仍夹在 min/max）。 */
dz_err_t servo_set_us(servo_t *s, uint16_t us);
/** 速率限制推进，dt_s 秒。 */
dz_err_t servo_tick(servo_t *s, float dt_s);
/** 角度→脉宽（纯函数，便于测试）。 */
uint16_t servo_deg_to_us(const servo_cfg_t *c, float deg);
dz_err_t servo_selftest(void);
#endif
