/**
 * @file foc.c
 * @brief 【已停用 2.0.0，2026-10-31】原实现写作时参照了 GPL-3.0 的 pid_helper 例程 foc_dev.c，无法排除派生，已整体移除。
 *        这里只保留接口：所有函数输出零占空比 / 零值，init 与各 step 返回 DZ_ENOTSUP，电机不会被驱动。
 *        待按 docs/参考来源.md“待净室重写清单”由未看过 pid_helper 源码的人重写。
 */
#include <string.h>
#include "foc.h"

static void zero3(float duty[3]) { if (duty) { duty[0] = duty[1] = duty[2] = 0.0f; } }

void foc_clarke(float ia, float ib, float *alpha, float *beta) { (void)ia; (void)ib; if (alpha) *alpha = 0.0f; if (beta) *beta = 0.0f; }
void foc_park(float alpha, float beta, float th_e, float *d, float *q) { (void)alpha; (void)beta; (void)th_e; if (d) *d = 0.0f; if (q) *q = 0.0f; }
void foc_ipark(float d, float q, float th_e, float *alpha, float *beta) { (void)d; (void)q; (void)th_e; if (alpha) *alpha = 0.0f; if (beta) *beta = 0.0f; }
void foc_svpwm(float alpha, float beta, float vbus, float duty[3]) { (void)alpha; (void)beta; (void)vbus; zero3(duty); }
float foc_norm_angle(float a) { (void)a; return 0.0f; }

dz_err_t foc_init(foc_t *f, const foc_cfg_t *cfg)
{
    if (f) { memset(f, 0, sizeof *f); if (cfg) f->cfg = *cfg; f->state = FOC_FAULT; }
    return DZ_ENOTSUP;
}
float foc_elec_angle(const foc_t *f, float mech) { (void)f; (void)mech; return 0.0f; }
void foc_set_voltage(const foc_t *f, float uq, float ud, float th_e, float duty[3]) { (void)f; (void)uq; (void)ud; (void)th_e; zero3(duty); }
dz_err_t foc_align_step(foc_t *f, float mech, float dt, float duty[3]) { (void)f; (void)mech; (void)dt; zero3(duty); return DZ_ENOTSUP; }
dz_err_t foc_set_calibration(foc_t *f, float zero_e, int8_t dir) { (void)f; (void)zero_e; (void)dir; return DZ_ENOTSUP; }
void foc_openloop_step(foc_t *f, float vel_mech, float uq, float dt, float duty[3]) { (void)f; (void)vel_mech; (void)uq; (void)dt; zero3(duty); }
dz_err_t foc_angle_step(foc_t *f, float target, float mech, float vel, float dt, float duty[3]) { (void)f; (void)target; (void)mech; (void)vel; (void)dt; zero3(duty); return DZ_ENOTSUP; }
dz_err_t foc_velocity_step(foc_t *f, float vel_target, float mech, float vel, float dt, float duty[3]) { (void)f; (void)vel_target; (void)mech; (void)vel; (void)dt; zero3(duty); return DZ_ENOTSUP; }
dz_err_t foc_pos_step(foc_t *f, float target, float mech, float vel, float dt, float duty[3]) { (void)f; (void)target; (void)mech; (void)vel; (void)dt; zero3(duty); return DZ_ENOTSUP; }
void foc_duty_to_pal(const float duty[3], uint16_t out[3]) { (void)duty; if (out) { out[0] = out[1] = out[2] = 0u; } }
dz_err_t foc_selftest(void) { return DZ_ENOTSUP; }
