/**
 * @file foc.h
 * @brief 电压型 FOC（无电流采样）：Clarke / Park / 反 Park、SVPWM、开环速度、角度闭环、上电对齐（零电角度 + 方向 + 极对数检查）。
 *
 * 纯 C、无硬件依赖：输入机械角（rad，多圈连续，例如 as5600_angle_multi），输出三相占空比 0..1，
 * 调用方自己写 PWM（pal_pwm_set 等）。全部非阻塞，按固定周期 dt 调用。
 * 参考：SimpleFOC (Arduino-FOC) BLDCMotor::setPhaseVoltage / alignSensor 思路；pid_helper 例程 foc_dev.c（对齐重试、电角度计算）。
 * 版本：FOC_VERSION
 */
#ifndef FOC_H
#define FOC_H
#include <stdint.h>
#include "dz_err.h"
#define FOC_VERSION "1.0.0"

void foc_clarke(float ia, float ib, float *alpha, float *beta);          /**< 两相电流（ic = -ia-ib） */
void foc_park(float alpha, float beta, float th_e, float *d, float *q);
void foc_ipark(float d, float q, float th_e, float *alpha, float *beta);
/** SVPWM（中点注入，等效七段式）：αβ 电压 → 三相占空比 0..1，超出六边形时按比例缩回。 */
void foc_svpwm(float alpha, float beta, float vbus, float duty[3]);
float foc_norm_angle(float a);                                           /**< → [0, 2π) */

typedef enum { FOC_IDLE, FOC_ALIGN, FOC_READY, FOC_FAULT } foc_state_t;

typedef struct {
    uint8_t pole_pairs;
    float vbus;          /**< 母线电压 V */
    float v_limit;       /**< Uq/Ud 上限 V（≤ vbus/√3） */
    float v_align;       /**< 对齐电压，0 = v_limit/2 */
    float t_align_s;     /**< 每段时间，0 = 0.5 s */
    float kp, ki, kd;    /**< 角度环：误差 rad → Uq V */
} foc_cfg_t;

typedef struct {
    foc_cfg_t cfg;
    foc_state_t state;
    int8_t dir;          /**< 传感器方向相对电角度：+1 / -1 */
    float zero_e;        /**< 零电角度 */
    float pp_est;        /**< 对齐时估出的极对数 */
    /* 对齐内部 */
    uint8_t phase; float t, a0, a1;
    /* 开环 / 闭环 */
    float ol_angle, integ, uq;
} foc_t;

dz_err_t foc_init(foc_t *f, const foc_cfg_t *cfg);
/** 电角度（READY 后有效）。 */
float foc_elec_angle(const foc_t *f, float mech);
/** 给定 Uq/Ud 和电角度出占空比。 */
void foc_set_voltage(const foc_t *f, float uq, float ud, float th_e, float duty[3]);
/** 对齐一步：DZ_EBUSY = 还在进行；DZ_OK = 完成（READY）；DZ_EFAIL = 不动 / 极对数不符（FAULT，pp_est 给估计值）。 */
dz_err_t foc_align_step(foc_t *f, float mech, float dt, float duty[3]);
/** 已知零点时跳过对齐。 */
dz_err_t foc_set_calibration(foc_t *f, float zero_e, int8_t dir);
/** 开环速度（不需要传感器、不需要对齐）：电角度按 vel_mech*pp 前进，Uq 固定。 */
void foc_openloop_step(foc_t *f, float vel_mech, float uq, float dt, float duty[3]);
/** 角度闭环（PID → Uq，限幅 + 积分抗饱和）。vel 可用 as5600_velocity。需 READY。 */
dz_err_t foc_angle_step(foc_t *f, float target, float mech, float vel, float dt, float duty[3]);
dz_err_t foc_selftest(void);
#endif
