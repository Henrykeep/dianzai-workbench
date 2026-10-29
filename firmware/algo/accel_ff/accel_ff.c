#include <math.h>
#include "accel_ff.h"

#define AFF_RAD2DEG 57.29578f
#define AFF_G_MPS2  9.80665f

float accel_ff_deg(const accel_ff_cfg_t *c, float a, bool valid)
{
    float y;
    if (!c || c->gain == 0.0f || !valid) return 0.0f;
    if (!(a == a) || fabsf(a) > c->fail_mps2) return 0.0f;          /* NaN / 读数异常 */
    if (fabsf(a) < c->dead_mps2) return 0.0f;                         /* 死区 */
    a -= a > 0.0f ? c->dead_mps2 : -c->dead_mps2;                     /* 死区边沿连续 */
    y = a / AFF_G_MPS2 * AFF_RAD2DEG * c->gain;
    return y > c->max_deg ? c->max_deg : (y < -c->max_deg ? -c->max_deg : y);
}

dz_err_t accel_ff_selftest(void)
{
    accel_ff_cfg_t c = { 1.0f, 0.0f, 50.0f, 90.0f };
    float y = accel_ff_deg(&c, AFF_G_MPS2 * 0.1f, true);
    if (fabsf(y - 5.729578f) > 1e-3f) return DZ_EINVAL;
    if (accel_ff_deg(&c, 1.0f, false) != 0.0f) return DZ_EINVAL;
    return DZ_OK;
}
