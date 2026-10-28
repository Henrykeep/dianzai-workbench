#include "battery.h"

battery_cfg_t battery_cfg_default(pal_id_t adc)
{
    battery_cfg_t c = { adc, 0u, 0u, 2u, 7000u, 6600u, 150u, 2000u, 1000u, 0.5f };
    return c;
}

const char *battery_state_name(battery_state_t s)
{
    switch (s) { case BAT_OK: return "OK"; case BAT_LOW: return "LOW"; case BAT_CRIT: return "CRIT"; default: return "NONE"; }
}

dz_err_t battery_init(battery_t *b, const battery_cfg_t *c)
{
    if (!b || !c) return DZ_EINVAL;
    b->ready = 0;
    if (c->crit_mv == 0u || c->crit_mv >= c->low_mv || c->hyst_mv >= c->low_mv) return DZ_EINVAL;
    if ((c->div_num == 0u) != (c->div_den == 0u) || !(c->lpf_tau_s >= 0.0f) || c->cells > 12u) return DZ_EINVAL;
    pal_adc_info_t inf = { 12u, 3300u, 1u, 1u };
    if (c->adc != PAL_ID_NONE) {
        dz_err_t e = pal_adc_info(c->adc, &inf);
        if (e != DZ_OK) return e;
    }
    if (inf.bits == 0u || inf.bits > 16u || inf.scale_den == 0u) return DZ_EINVAL;
    b->cfg = *c;
    b->num = c->div_num ? c->div_num : inf.scale_num;
    b->den = c->div_den ? c->div_den : inf.scale_den;
    b->full_code = (1u << inf.bits) - 1u;
    b->vref_mv = inf.vref_mv;
    b->mv = 0.0f; b->state = b->cand = BAT_NONE; b->cand_since = 0; b->last_ms = 0; b->primed = 0;
    b->ready = 1;
    return DZ_OK;
}

static battery_state_t classify(const battery_t *b, float mv)
{
    const battery_cfg_t *c = &b->cfg;
    if (mv < (float)c->absent_mv) return BAT_NONE;
    /* 从差状态恢复要多出 hyst */
    float h = (float)c->hyst_mv;
    if (mv < (float)c->crit_mv + (b->state == BAT_CRIT ? h : 0.0f)) return BAT_CRIT;
    if (mv < (float)c->low_mv + ((b->state == BAT_LOW || b->state == BAT_CRIT) ? h : 0.0f)) return BAT_LOW;
    return BAT_OK;
}

dz_err_t battery_feed_raw(battery_t *b, uint16_t raw, uint32_t now_ms)
{
    if (!b || !b->ready) return DZ_ESTATE;
    if (raw > b->full_code) return DZ_EINVAL;
    float mv = (float)raw / (float)b->full_code * (float)b->vref_mv * (float)b->num / (float)b->den;
    if (!b->primed) { b->mv = mv; b->primed = 1; b->state = classify(b, mv); b->cand = b->state; }
    else {
        float dt = (float)(uint32_t)(now_ms - b->last_ms) * 0.001f;
        float a = b->cfg.lpf_tau_s > 0.0f ? dt / (b->cfg.lpf_tau_s + dt) : 1.0f;
        b->mv += a * (mv - b->mv);
    }
    b->last_ms = now_ms;
    battery_state_t s = classify(b, b->mv);
    if (s == b->state) { b->cand = s; return DZ_OK; }
    /* 拔电池（NONE）立即生效；其余需持续 hold_ms */
    if (s != b->cand) { b->cand = s; b->cand_since = now_ms; }
    if (s == BAT_NONE || (uint32_t)(now_ms - b->cand_since) >= b->cfg.hold_ms) b->state = s;
    return DZ_OK;
}

dz_err_t battery_update(battery_t *b, uint32_t now_ms)
{
    if (!b || !b->ready) return DZ_ESTATE;
    uint16_t raw = 0;
    dz_err_t e = pal_adc_read(b->cfg.adc, &raw);
    if (e != DZ_OK) return e;
    return battery_feed_raw(b, raw, now_ms);
}

float battery_mv(const battery_t *b) { return b ? b->mv : 0.0f; }
battery_state_t battery_state(const battery_t *b) { return b ? b->state : BAT_NONE; }

int battery_percent(const battery_t *b)
{
    if (!b || b->cfg.cells == 0u || b->state == BAT_NONE) return -1;
    /* 单节锂电空载近似：电压-电量分段线性（负载下会偏低，仅作显示） */
    static const uint16_t mv_tab[] = { 3300, 3600, 3700, 3750, 3800, 3900, 4000, 4100, 4200 };
    static const uint8_t  pc_tab[] = {    0,    5,   15,   30,   45,   65,   80,   92,  100 };
    float cell = b->mv / (float)b->cfg.cells;
    if (cell <= (float)mv_tab[0]) return 0;
    for (unsigned i = 1; i < sizeof mv_tab / sizeof mv_tab[0]; i++) {
        if (cell <= (float)mv_tab[i]) {
            float t = (cell - (float)mv_tab[i - 1]) / (float)(mv_tab[i] - mv_tab[i - 1]);
            return (int)((float)pc_tab[i - 1] + t * (float)(pc_tab[i] - pc_tab[i - 1]) + 0.5f);
        }
    }
    return 100;
}

dz_err_t battery_selftest(void)
{
    battery_t b; battery_cfg_t c = battery_cfg_default(PAL_ID_NONE);
    c.div_num = 11u; c.div_den = 1u; c.lpf_tau_s = 0.0f;
    if (battery_init(&b, &c) != DZ_OK) return DZ_EFAIL;
    /* 8.0 V / 11 = 727 mV → raw = 727/3300*4095 ≈ 903 */
    (void)battery_feed_raw(&b, 903u, 0);
    if (b.state != BAT_OK || b.mv < 7950.0f || b.mv > 8050.0f) return DZ_EFAIL;
    (void)battery_feed_raw(&b, 780u, 100);   /* ~7.0 V 以下 */
    if (b.state != BAT_OK) return DZ_EFAIL;  /* 未到保持时间 */
    (void)battery_feed_raw(&b, 780u, 2200);
    if (b.state != BAT_LOW) return DZ_EFAIL;
    return DZ_OK;
}
