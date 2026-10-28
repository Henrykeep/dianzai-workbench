#include "encoder.h"
#include "dz_wrap.h"

static bool enc_finite(float x) { return (x == x) && (x - x == 0.0f); }

encoder_cfg_t encoder_cfg_default(void)
{
    encoder_cfg_t c;
    c.enc = PAL_ID_NONE;
    c.counts_per_rev = 0.0f;
    c.dt_s = 0.0f;
    c.speed_lpf_hz = 0.0f;
    c.invert = false;
    c.window_n = 1u;
    return c;
}

dz_err_t encoder_init(encoder_t *e, const encoder_cfg_t *cfg)
{
    if (e == 0 || cfg == 0) return DZ_EINVAL;
    if (cfg->enc == PAL_ID_NONE) return DZ_EINVAL;
    if (!enc_finite(cfg->counts_per_rev) || cfg->counts_per_rev <= 0.0f) return DZ_EINVAL;
    if (!enc_finite(cfg->dt_s) || cfg->dt_s <= 0.0f) return DZ_EINVAL;
    if (!enc_finite(cfg->speed_lpf_hz) || cfg->speed_lpf_hz < 0.0f) return DZ_EINVAL;
    if (cfg->window_n > ENCODER_WINDOW_MAX) return DZ_EINVAL;

    bool use_lpf = cfg->speed_lpf_hz > 0.0f;
    if (use_lpf) {
        lpf1_cfg_t lc = { cfg->speed_lpf_hz, cfg->dt_s };
        if (lpf1_init(&e->lpf, &lc) != DZ_OK) return DZ_EINVAL;
    }
    int32_t now;
    dz_err_t r = pal_enc_get_count(cfg->enc, &now);
    if (r != DZ_OK) return r;

    e->cfg = *cfg;
    e->use_lpf = use_lpf;
    e->last_count = now;
    e->total = 0;
    e->last_delta = 0;
    e->speed_rps = 0.0f;
    e->win_sum = 0; e->win_i = 0; e->win_fill = 0;
    e->ready = true;
    return DZ_OK;
}

dz_err_t encoder_update(encoder_t *e)
{
    if (e == 0 || !e->ready) return DZ_ESTATE;
    int32_t now;
    dz_err_t r = pal_enc_get_count(e->cfg.enc, &now);
    if (r != DZ_OK) return r;
    /* 无符号相减再转回有符号：即使 32 位计数回绕也得到正确增量 */
    int32_t delta = dz_wrap32_delta((uint32_t)now, (uint32_t)e->last_count);
    e->last_count = now;
    if (e->cfg.invert) delta = -delta;
    e->last_delta = delta;
    e->total += delta;
    float rps;
    uint8_t n = e->cfg.window_n > 1u ? e->cfg.window_n : 1u;
    if (n > 1u) {                                  /* 滑动窗口：最近 n 个周期的总计数 / (n·dt) */
        if (e->win_fill == n) e->win_sum -= e->win[e->win_i]; else e->win_fill++;
        e->win[e->win_i] = delta; e->win_sum += delta;
        e->win_i = (uint8_t)((e->win_i + 1u) % n);
        rps = (float)e->win_sum / e->cfg.counts_per_rev / (e->cfg.dt_s * (float)e->win_fill);
    } else {
        rps = (float)delta / e->cfg.counts_per_rev / e->cfg.dt_s;
    }
    e->speed_rps = e->use_lpf ? lpf1_update(&e->lpf, rps) : rps;
    return DZ_OK;
}

float encoder_speed_rps(const encoder_t *e) { return (e && e->ready) ? e->speed_rps : 0.0f; }
float encoder_speed_rpm(const encoder_t *e) { return encoder_speed_rps(e) * 60.0f; }

float encoder_position_rev(const encoder_t *e)
{
    if (e == 0 || !e->ready) return 0.0f;
    return (float)((double)e->total / (double)e->cfg.counts_per_rev);
}

int64_t encoder_count(const encoder_t *e) { return (e && e->ready) ? e->total : 0; }
int32_t encoder_last_delta(const encoder_t *e) { return (e && e->ready) ? e->last_delta : 0; }

void encoder_zero(encoder_t *e)
{
    if (e == 0 || !e->ready) return;
    e->total = 0;
}

dz_err_t encoder_selftest_still(encoder_t *e, uint32_t duration_ms, int32_t max_jitter)
{
    if (e == 0 || !e->ready) return DZ_ESTATE;
    if (max_jitter < 0) return DZ_EINVAL;
    int32_t start, now;
    dz_err_t r = pal_enc_get_count(e->cfg.enc, &start);
    if (r != DZ_OK) return r;
    now = start;
    uint32_t t0 = pal_millis();
    int32_t worst = 0;
    while ((uint32_t)(pal_millis() - t0) < duration_ms) {
        r = pal_enc_get_count(e->cfg.enc, &now);
        if (r != DZ_OK) return r;
        int32_t d = (int32_t)((uint32_t)now - (uint32_t)start);
        if (d < 0) d = -d;
        if (d > worst) worst = d;
        pal_delay_ms(1);
    }
    /* 自检期间直接读了计数，把基准同步一下，避免下一次 update 出现大增量 */
    e->last_count = now;
    return worst > max_jitter ? DZ_EFAIL : DZ_OK;
}
