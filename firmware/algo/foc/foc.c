/* FOC，见 foc.h。 */
#include "foc.h"
#include <math.h>
#include <string.h>

#define PI_F 3.14159265359f
#define TWO_PI 6.28318530718f
#define SQRT3 1.73205080757f

void foc_clarke(float ia, float ib, float *alpha, float *beta)
{ *alpha = ia; *beta = (ia + 2.0f * ib) / SQRT3; }

void foc_park(float al, float be, float th, float *d, float *q)
{ float c = cosf(th), s = sinf(th); *d = al * c + be * s; *q = -al * s + be * c; }

void foc_ipark(float d, float q, float th, float *al, float *be)
{ float c = cosf(th), s = sinf(th); *al = d * c - q * s; *be = d * s + q * c; }

float foc_norm_angle(float a)
{ a = fmodf(a, TWO_PI); return a < 0.0f ? a + TWO_PI : a; }

void foc_svpwm(float al, float be, float vbus, float duty[3])
{
    float va = al, vb = -0.5f * al + 0.5f * SQRT3 * be, vc = -0.5f * al - 0.5f * SQRT3 * be;
    float mx = fmaxf(va, fmaxf(vb, vc)), mn = fminf(va, fminf(vb, vc));
    float span = mx - mn, k = 1.0f;
    if (vbus <= 0.0f) { duty[0] = duty[1] = duty[2] = 0.0f; return; }
    if (span > vbus) k = vbus / span;                /* 超出六边形：等比例缩 */
    float mid = 0.5f * (mx + mn) * k;                 /* 中点注入 = SVPWM */
    float v[3] = { va, vb, vc };
    for (int i = 0; i < 3; i++) {
        float d = 0.5f + (v[i] * k - mid) / vbus;
        duty[i] = d < 0.0f ? 0.0f : d > 1.0f ? 1.0f : d;
    }
}

dz_err_t foc_init(foc_t *f, const foc_cfg_t *c)
{
    if (!f || !c || c->pole_pairs == 0 || c->vbus <= 0.0f || c->v_limit <= 0.0f) return DZ_EINVAL;
    memset(f, 0, sizeof *f);
    f->cfg = *c;
    if (f->cfg.v_limit > c->vbus / SQRT3) f->cfg.v_limit = c->vbus / SQRT3;
    if (f->cfg.v_align <= 0.0f || f->cfg.v_align > f->cfg.v_limit) f->cfg.v_align = f->cfg.v_limit * 0.5f;
    if (f->cfg.t_align_s <= 0.0f) f->cfg.t_align_s = 0.5f;
    f->dir = 1;
    f->state = FOC_IDLE;
    return DZ_OK;
}

float foc_elec_angle(const foc_t *f, float mech)
{ return foc_norm_angle((float)f->dir * (float)f->cfg.pole_pairs * mech - f->zero_e); }

void foc_set_voltage(const foc_t *f, float uq, float ud, float th, float duty[3])
{
    float al, be;
    foc_ipark(ud, uq, th, &al, &be);
    foc_svpwm(al, be, f->cfg.vbus, duty);
}

/* 对齐：0 保持 θe=0 → 1 正扫一个电周期 → 2 反扫回来 → 3 保持 θe=0 → 记零点。 */
dz_err_t foc_align_step(foc_t *f, float mech, float dt, float duty[3])
{
    if (!f || dt <= 0.0f) return DZ_EINVAL;
    if (f->state != FOC_ALIGN) { f->state = FOC_ALIGN; f->phase = 0; f->t = 0.0f; }
    float T = f->cfg.t_align_s, th = 0.0f;
    f->t += dt;
    if (f->phase == 1) th = TWO_PI * f->t / T;
    else if (f->phase == 2) th = TWO_PI * (1.0f - f->t / T);
    foc_set_voltage(f, 0.0f, f->cfg.v_align, th, duty);
    if (f->t < T) return DZ_EBUSY;
    f->t = 0.0f;
    switch (f->phase) {
    case 0: f->a0 = mech; f->phase = 1; return DZ_EBUSY;
    case 1: f->a1 = mech; f->phase = 2; return DZ_EBUSY;
    case 2: f->phase = 3; return DZ_EBUSY;
    default: break;
    }
    float moved = f->a1 - f->a0;
    float am = fabsf(moved);
    f->pp_est = am > 1e-6f ? TWO_PI / am : 0.0f;
    duty[0] = duty[1] = duty[2] = 0.0f;
    if (am < 0.1f * TWO_PI / f->cfg.pole_pairs) { f->state = FOC_FAULT; return DZ_EFAIL; }   /* 没转：没接 / 电压不够 */
    if (fabsf(f->pp_est - f->cfg.pole_pairs) > 0.3f * f->cfg.pole_pairs) { f->state = FOC_FAULT; return DZ_EFAIL; }
    f->dir = moved > 0.0f ? 1 : -1;
    f->zero_e = 0.0f;
    f->zero_e = foc_elec_angle(f, mech);            /* 转子 d 轴此刻对准 θe=0 */
    f->integ = 0.0f;
    f->state = FOC_READY;
    return DZ_OK;
}

dz_err_t foc_set_calibration(foc_t *f, float zero_e, int8_t dir)
{
    if (!f || (dir != 1 && dir != -1)) return DZ_EINVAL;
    f->zero_e = foc_norm_angle(zero_e); f->dir = dir; f->integ = 0.0f; f->state = FOC_READY;
    return DZ_OK;
}

static float clampv(const foc_t *f, float u)
{ float l = f->cfg.v_limit; return u > l ? l : u < -l ? -l : u; }

void foc_openloop_step(foc_t *f, float vel, float uq, float dt, float duty[3])
{
    f->ol_angle = foc_norm_angle(f->ol_angle + vel * (float)f->cfg.pole_pairs * dt);
    f->uq = clampv(f, uq);
    foc_set_voltage(f, f->uq, 0.0f, f->ol_angle, duty);
}

dz_err_t foc_angle_step(foc_t *f, float target, float mech, float vel, float dt, float duty[3])
{
    if (!f || dt <= 0.0f) return DZ_EINVAL;
    if (f->state != FOC_READY) { duty[0] = duty[1] = duty[2] = 0.0f; return DZ_ESTATE; }
    float e = target - mech;
    float u = f->cfg.kp * e + f->integ - f->cfg.kd * vel;
    float uc = clampv(f, u);
    if (u == uc || (u > uc) != (e > 0.0f)) f->integ = clampv(f, f->integ + f->cfg.ki * e * dt);   /* 饱和时不往同方向积 */
    f->uq = clampv(f, f->cfg.kp * e + f->integ - f->cfg.kd * vel);
    foc_set_voltage(f, (float)f->dir * f->uq, 0.0f, foc_elec_angle(f, mech), duty);   /* 传感器反装时正 Uq 让读数减小 */
    return DZ_OK;
}

dz_err_t foc_selftest(void)
{
    float al, be, d, q, du[3];
    foc_ipark(0.3f, 0.7f, 1.0f, &al, &be);
    foc_park(al, be, 1.0f, &d, &q);
    if (fabsf(d - 0.3f) > 1e-4f || fabsf(q - 0.7f) > 1e-4f) return DZ_EFAIL;
    foc_svpwm(0.0f, 0.0f, 12.0f, du);
    return fabsf(du[0] - 0.5f) < 1e-6f && fabsf(du[2] - 0.5f) < 1e-6f ? DZ_OK : DZ_EFAIL;
}
