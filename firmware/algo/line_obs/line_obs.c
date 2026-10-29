/* 丢线观测与找线恢复，见 line_obs.h。 */
#include <math.h>
#include <string.h>
#include "line_obs.h"

line_obs_cfg_t line_obs_cfg_default(void)
{
    line_obs_cfg_t c = { .lost_confirm = 3u, .dir_frames = 4u, .reacq_frames = 10u,
                         .lost_timeout_ms = 12000u, .center_band = 0.0f };
    return c;
}

dz_err_t line_obs_init(line_obs_t *o, const line_obs_cfg_t *c)
{
    if (!o || !c || !c->lost_confirm || !c->reacq_frames || !c->dir_frames || c->dir_frames > LINE_OBS_DIR_MAX ||
        !(c->center_band >= 0.0f))
        return DZ_EINVAL;
    memset(o, 0, sizeof *o);
    o->c = *c;
    return DZ_OK;
}

void line_obs_reset(line_obs_t *o)
{
    line_obs_cfg_t c = o->c;
    uint32_t n = o->lost_count;
    (void)line_obs_init(o, &c);
    o->lost_count = n;
}

static int8_t dir_from_hist(const line_obs_t *o)
{
    float s = 0.0f;
    uint8_t i;
    if (!o->hn) return 0;
    for (i = 0; i < o->hn; i++) s += o->hist[i];
    s /= (float)o->hn;
    if (fabsf(s) <= o->c.center_band) return 0;
    return s < 0.0f ? -1 : 1;
}

line_obs_state_t line_obs_update(line_obs_t *o, bool seen, float pos, bool cross, uint32_t now_ms)
{
    o->just = false;
    if (o->st == LINE_OBS_FAIL) return o->st;
    if (seen && !isfinite(pos)) seen = false;
    if (cross) seen = true;
    if (o->st == LINE_OBS_LOST) {
        o->seen = (seen && !cross) ? (uint8_t)(o->seen + (o->seen < 255u)) : 0u;
        if (o->seen >= o->c.reacq_frames) { o->st = LINE_OBS_TRACK; o->miss = 0; o->hn = o->hi = 0; }
        else if (o->c.lost_timeout_ms && (uint32_t)(now_ms - o->t_lost) >= o->c.lost_timeout_ms) o->st = LINE_OBS_FAIL;
        return o->st;
    }
    if (!seen) {
        if (++o->miss >= o->c.lost_confirm) {
            o->st = LINE_OBS_LOST; o->t_lost = now_ms; o->seen = 0;
            o->dir = dir_from_hist(o); o->lost_count++; o->just = true;
        }
        return o->st;
    }
    o->miss = 0;
    if (cross) { o->st = LINE_OBS_WIDE; return o->st; }
    o->st = LINE_OBS_TRACK;
    o->hist[o->hi] = pos;
    o->hi = (uint8_t)((o->hi + 1u) % o->c.dir_frames);
    if (o->hn < o->c.dir_frames) o->hn++;
    return o->st;
}

bool line_obs_just_lost(const line_obs_t *o) { return o->just; }
int8_t line_obs_dir(const line_obs_t *o) { return o->dir; }

dz_err_t line_obs_selftest(void)
{
    line_obs_t o;
    line_obs_cfg_t c = line_obs_cfg_default();
    uint32_t t = 0;
    int fail = 0, i;
    if (line_obs_init(&o, &c) != DZ_OK) return DZ_EINVAL;
    for (i = 0; i < 6; i++) line_obs_update(&o, true, 5.0f + (float)i, false, t++);   /* 线偏右 */
    fail += line_obs_update(&o, false, 0, false, t++) != LINE_OBS_TRACK;              /* 抖一拍不算 */
    line_obs_update(&o, true, 8.0f, false, t++);
    line_obs_update(&o, false, 0, false, t++); line_obs_update(&o, false, 0, false, t++);
    fail += line_obs_update(&o, false, 0, false, t++) != LINE_OBS_LOST || line_obs_dir(&o) != 1 || o.lost_count != 1u || !line_obs_just_lost(&o);
    for (i = 0; i < 9; i++) fail += line_obs_update(&o, true, 0.0f, false, t++) != LINE_OBS_LOST;
    fail += line_obs_update(&o, true, 0.0f, false, t++) != LINE_OBS_TRACK;            /* 第 10 拍找回 */
    fail += line_obs_update(&o, true, 0.0f, true, t++) != LINE_OBS_WIDE;              /* 路口不算丢 */
    for (i = 0; i < 3; i++) line_obs_update(&o, false, 0, false, t);
    fail += line_obs_update(&o, false, 0, false, t + 12000u) != LINE_OBS_FAIL;        /* 12 s 超时 */
    fail += line_obs_update(&o, true, 0.0f, false, t + 12001u) != LINE_OBS_FAIL;      /* 锁存 */
    line_obs_reset(&o);
    fail += o.st != LINE_OBS_TRACK || o.lost_count != 2u;
    c.dir_frames = 0; fail += line_obs_init(&o, &c) != DZ_EINVAL;
    return fail ? DZ_EINVAL : DZ_OK;
}
