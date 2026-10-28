#include "vis.h"
#include <math.h>
#include <stddef.h>

dz_err_t vis_link_init(vis_link_t *l, const vis_link_cfg_t *cfg)
{
    if (!l || !cfg || cfg->hold_ms == 0u || cfg->lost_ms <= cfg->hold_ms) return DZ_EINVAL;
    *l = (vis_link_t){0};
    l->cfg = *cfg;
    return DZ_OK;
}

void vis_link_feed(vis_link_t *l, uint8_t seq, uint32_t cam_ms, uint32_t rx_ms, bool valid, float x)
{
    if (!l) return;
    l->frames++;
    if (l->have_seq) {
        uint8_t gap = (uint8_t)(seq - l->last_seq);
        if (gap == 0u) return;                          /* 重复帧 */
        if (gap < 128u) l->drops += gap - 1u;           /* 大跳（>=128）当作对端重启，不计入丢帧 */
    }
    l->have_seq = true;
    l->last_seq = seq;
    if (!valid || !isfinite(x)) { l->invalid++; return; }
    int32_t off = (int32_t)(rx_ms - cam_ms);
    if (l->win_n == 0u) { l->off_min = off; l->off_min_next = off; }
    if (off < l->off_min) l->off_min = off;
    if (off < l->off_min_next) l->off_min_next = off;
    l->win_n++;
    if (l->cfg.lat_win && l->win_n >= l->cfg.lat_win) {  /* 窗口滚动：用后半窗口的最小值接替 */
        l->off_min = l->off_min_next; l->off_min_next = off; l->win_n = 1u;
    }
    l->lat_jitter_ms = off - l->off_min;
    l->have = true;
    l->last_rx_ms = rx_ms;
    l->last_cam_ms = cam_ms;
    l->x = x;
}

uint32_t vis_link_age_ms(const vis_link_t *l, uint32_t now_ms)
{
    if (!l || !l->have) return UINT32_MAX;
    return now_ms - l->last_rx_ms;
}

vis_state_t vis_link_poll(const vis_link_t *l, uint32_t now_ms)
{
    uint32_t age = vis_link_age_ms(l, now_ms);
    if (age == UINT32_MAX || age > l->cfg.lost_ms) return VIS_LOST;
    return age > l->cfg.hold_ms ? VIS_HELD : VIS_VALID;
}

const char *vis_state_name(vis_state_t s)
{
    return s == VIS_VALID ? "valid" : s == VIS_HELD ? "held" : "lost";
}

dz_err_t vis_calib_init(vis_calib_t *c, const float *px, const float *val, uint8_t n)
{
    if (!c || !px || !val || n < 2u || n > VIS_CALIB_MAX) return DZ_EINVAL;
    for (uint8_t i = 0; i < n; i++) {
        if (!isfinite(px[i]) || !isfinite(val[i])) return DZ_EINVAL;
        if (i && !(px[i] > px[i - 1u])) return DZ_EINVAL;
    }
    c->n = n;
    for (uint8_t i = 0; i < n; i++) { c->px[i] = px[i]; c->val[i] = val[i]; }
    return DZ_OK;
}

float vis_calib_apply(const vis_calib_t *c, float px, bool *out_of_range)
{
    if (out_of_range) *out_of_range = false;
    if (!c || c->n < 2u || !isfinite(px)) return 0.0f;
    uint8_t i = 1u;
    while (i < c->n - 1u && px > c->px[i]) i++;        /* 段 [i-1, i]；两端外推用最外侧段 */
    if (out_of_range && (px < c->px[0] || px > c->px[c->n - 1u])) *out_of_range = true;
    float k = (c->val[i] - c->val[i - 1u]) / (c->px[i] - c->px[i - 1u]);
    return c->val[i - 1u] + k * (px - c->px[i - 1u]);
}

dz_err_t vis_selftest(void)
{
    vis_link_t l; vis_link_cfg_t cfg = { 50u, 200u, 0u };
    if (vis_link_init(&l, &cfg) != DZ_OK || vis_link_poll(&l, 0) != VIS_LOST) return DZ_EFAIL;
    vis_link_feed(&l, 1, 100, 130, true, 5.0f);
    if (vis_link_poll(&l, 140) != VIS_VALID || vis_link_poll(&l, 200) != VIS_HELD || vis_link_poll(&l, 400) != VIS_LOST) return DZ_EFAIL;
    float px[4] = { -100, -10, 10, 100 }, mm[4] = { -60, -5, 5, 40 };
    vis_calib_t c;
    if (vis_calib_init(&c, px, mm, 4) != DZ_OK) return DZ_EFAIL;
    bool oor;
    if (fabsf(vis_calib_apply(&c, 0, &oor)) > 1e-4f || oor) return DZ_EFAIL;
    return fabsf(vis_calib_apply(&c, 55, &oor) - 22.5f) < 1e-3f ? DZ_OK : DZ_EFAIL;
}
