#include <math.h>
#include "attitude.h"

#define G_MPS2 9.80665f

dz_err_t attitude_init(attitude_t *a, float tau_s, float acc_gate)
{
    if (!a || !(tau_s > 0.0f) || !(acc_gate > 0.0f)) return DZ_EINVAL;
    *a = (attitude_t){ tau_s, acc_gate, 0.0f, 0.0f, false };
    return DZ_OK;
}

dz_err_t attitude_update(attitude_t *a, const float acc[3], const float gyr[3], float dt)
{
    if (!a || !acc || !gyr || !(dt > 0.0f) || dt > 1.0f) return DZ_EINVAL;
    for (int i = 0; i < 3; i++) if (!isfinite(acc[i]) || !isfinite(gyr[i])) return DZ_EINVAL;
    float an = sqrtf(acc[0] * acc[0] + acc[1] * acc[1] + acc[2] * acc[2]);
    bool acc_ok = fabsf(an / G_MPS2 - 1.0f) <= a->acc_gate;
    float r_acc = atan2f(acc[1], acc[2]);
    float p_acc = atan2f(-acc[0], sqrtf(acc[1] * acc[1] + acc[2] * acc[2]));
    if (!a->inited) {
        if (!acc_ok) return DZ_ESTATE;      /* 第一拍就在晃，没法定初值：等下一拍 */
        a->roll = r_acc; a->pitch = p_acc; a->inited = true;
        return DZ_OK;
    }
    /* 欧拉角运动学（小角度下近似 roll += gx、pitch += gy） */
    float sr = sinf(a->roll), cr = cosf(a->roll), cp = cosf(a->pitch), tp = tanf(a->pitch);
    if (fabsf(cp) < 1e-3f) cp = 1e-3f;
    float droll = gyr[0] + (gyr[1] * sr + gyr[2] * cr) * tp;
    float dpitch = gyr[1] * cr - gyr[2] * sr;
    a->roll += droll * dt;
    a->pitch += dpitch * dt;
    if (acc_ok) {
        float k = dt / (a->tau_s + dt);
        float er = r_acc - a->roll;
        if (er > 3.14159265f) er -= 6.2831853f; else if (er < -3.14159265f) er += 6.2831853f;
        a->roll += k * er;
        a->pitch += k * (p_acc - a->pitch);
    }
    return DZ_OK;
}

dz_err_t attitude_selftest(void)
{
    attitude_t a;
    if (attitude_init(&a, 0.5f, 0.15f)) return DZ_EFAIL;
    /* 静止倾斜 30°（绕 x）：加速度 (0, g sin30, g cos30)，带 0.05 rad/s 的陀螺零偏，2 s 后误差应很小 */
    const float acc[3] = { 0.0f, G_MPS2 * 0.5f, G_MPS2 * 0.8660254f }, gyr[3] = { 0.05f, 0.0f, 0.0f };
    for (int i = 0; i < 400; i++) if (attitude_update(&a, acc, gyr, 0.005f)) return DZ_EFAIL;
    /* 零偏 b 造成的稳态偏差 = b·tau = 0.025 rad */
    if (fabsf(a.roll - 0.5235988f - 0.025f) > 0.01f || fabsf(a.pitch) > 0.01f) return DZ_EFAIL;
    return DZ_OK;
}
