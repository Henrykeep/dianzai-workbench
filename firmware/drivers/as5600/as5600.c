/* AS5600 驱动，见 as5600.h。 */
#include "as5600.h"
#include <string.h>

#define TWO_PI 6.28318530718f
#define CPR 4096

dz_err_t as5600_init(as5600_t *e, const as5600_cfg_t *cfg)
{
    if (!e || !cfg || (cfg->dir != 1 && cfg->dir != -1) || cfg->vel_tau_s < 0.0f) return DZ_EINVAL;
    memset(e, 0, sizeof *e);
    e->cfg = *cfg;
    e->ready = true;
    return DZ_OK;
}

dz_err_t as5600_check_magnet(as5600_t *e, uint8_t *status)
{
    if (!e || !e->ready) return DZ_ESTATE;
    uint8_t s = 0;
    dz_err_t r = pal_i2c_mem_read(e->cfg.i2c, AS5600_ADDR, 0x0B, &s, 1);
    if (r != DZ_OK) { e->errors++; return r; }
    e->status = s;
    if (status) *status = s;
    if (!(s & 0x20u)) return DZ_ENODEV;
    if (s & 0x18u) return DZ_EFAIL;
    return DZ_OK;
}

static int32_t counts(const as5600_t *e)    /* 减零点、乘方向后的单圈计数 0..4095 */
{
    int32_t c = ((int32_t)e->raw - (int32_t)e->zero) * e->cfg.dir;
    return ((c % CPR) + CPR) % CPR;
}

dz_err_t as5600_update(as5600_t *e, uint32_t now_us)
{
    if (!e || !e->ready) return DZ_ESTATE;
    uint8_t b[2];
    dz_err_t r = pal_i2c_mem_read(e->cfg.i2c, AS5600_ADDR, 0x0C, b, 2);
    if (r != DZ_OK) { e->errors++; return r; }
    int32_t prev = e->has ? counts(e) : -1;
    e->raw = (uint16_t)(((uint16_t)(b[0] & 0x0Fu) << 8) | b[1]);
    int32_t c = counts(e);
    float prev_multi = e->angle_multi;
    if (prev >= 0) {
        int32_t d = c - prev;
        if (d > CPR / 2) e->turns--;
        else if (d < -CPR / 2) e->turns++;
    }
    e->angle = (float)c * (TWO_PI / CPR);
    e->angle_multi = (float)e->turns * TWO_PI + e->angle;
    if (e->has) {
        float dt = (float)(uint32_t)(now_us - e->t_us) * 1e-6f;
        if (dt > 0.0f) {
            float v = (e->angle_multi - prev_multi) / dt;
            float a = e->cfg.vel_tau_s > 0.0f ? dt / (e->cfg.vel_tau_s + dt) : 1.0f;
            e->vel += a * (v - e->vel);
        }
    }
    e->t_us = now_us;
    e->has = true;
    return DZ_OK;
}

dz_err_t as5600_set_zero_here(as5600_t *e)
{
    if (!e || !e->ready || !e->has) return DZ_ESTATE;
    e->zero = e->raw; e->turns = 0; e->angle = 0.0f; e->angle_multi = 0.0f;
    return DZ_OK;
}

dz_err_t as5600_selftest(void)
{
    as5600_t e; as5600_cfg_t c = { PAL_ID_NONE, -1, 0.0f };
    if (as5600_init(&e, &c) != DZ_OK) return DZ_EFAIL;
    e.raw = 100; e.zero = 0;
    return counts(&e) == CPR - 100 ? DZ_OK : DZ_EFAIL;    /* 反向：100 → 3996 */
}
