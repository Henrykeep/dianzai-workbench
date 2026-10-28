/**
 * 子系统 vision：从 io_in 取出新到达的视觉帧，经 firmware/algo/vision：
 *   vis_link —— VALID / HELD / LOST 三态、数据时效 age_ms、按 seq 计丢帧、相对延迟抖动；
 *   vis_calib —— cal_n ≥ 2 时把原始像素映射为“线性化像素”（分段线性，左右斜率独立）。
 * 读：io_in   写：vision_out
 * flags：bit0 有效才算样本；bit2 标定过期只做提示（不丢弃）。
 */
#include "project_gen.h"
#include "vis.h"

static uint32_t s_last_seq;
static vis_link_t s_vl;
static vis_calib_t s_cal;
static bool s_cal_ok;

static void load_cfg(const params_t *p)
{
    vis_link_cfg_t c = { p->vis_hold_ms, p->vis_lost_ms > p->vis_hold_ms ? p->vis_lost_ms : p->vis_hold_ms + 1u, 200u };
    if (c.hold_ms != s_vl.cfg.hold_ms || c.lost_ms != s_vl.cfg.lost_ms) {
        vis_link_t keep = s_vl;
        if (vis_link_init(&s_vl, &c) == DZ_OK && keep.cfg.hold_ms) { vis_link_cfg_t n = s_vl.cfg; s_vl = keep; s_vl.cfg = n; }
    }
    float px[5] = { p->cal_px0, p->cal_px1, p->cal_px2, p->cal_px3, p->cal_px4 };
    float v[5]  = { p->cal_v0, p->cal_v1, p->cal_v2, p->cal_v3, p->cal_v4 };
    s_cal_ok = p->cal_n >= 2u && vis_calib_init(&s_cal, px, v, p->cal_n) == DZ_OK;   /* 非法表 → 不标定（回退原始像素） */
}

static dz_err_t vision_init(void *state, const void *params)
{
    shared_state_t *st = state;
    st->vision_out = (st_vision_out_t){0};
    s_vl = (vis_link_t){0};
    load_cfg(params);
    s_last_seq = st->io_in.cam_seq;
    st->vision_out.age_ms = UINT32_MAX;
    return DZ_OK;
}

static void vision_step(void *state, const void *params, uint32_t now_ms)
{
    shared_state_t *st = state;
    load_cfg(params);
    st->vision_out.new_sample = false;
    if (st->io_in.cam_seq != s_last_seq) {
        bool valid = (st->io_in.cam_flags & 0x01u) != 0u;
        s_last_seq = st->io_in.cam_seq;
        vis_link_feed(&s_vl, st->io_in.cam_fseq, st->io_in.cam_ms, st->io_in.cam_rx_ms, valid, (float)st->io_in.cam_x_px);
        if (valid) {                                           /* 无效帧：不更新，钢珠环靠超时处理 */
            float raw = (float)st->io_in.cam_x_px;
            st->vision_out.new_sample = true;
            st->vision_out.x_raw_px = raw;
            st->vision_out.x_px = s_cal_ok ? vis_calib_apply(&s_cal, raw, 0) : raw;
            st->vision_out.t_ms = st->io_in.cam_rx_ms;
        }
    }
    st->vision_out.state = (uint8_t)vis_link_poll(&s_vl, now_ms);
    st->vision_out.age_ms = vis_link_age_ms(&s_vl, now_ms);
    st->vision_out.drops = s_vl.drops;
    st->vision_out.lat_jit_ms = s_vl.lat_jitter_ms;
}

static dz_err_t vision_selftest(void)
{
    shared_state_t st = {0};
    params_t p = {0};
    p.vis_hold_ms = 60u; p.vis_lost_ms = 300u;
    vision_init(&st, &p);
    st.io_in = (st_io_in_t){ .cam_x_px = -20, .cam_flags = 0x09, .cam_seq = 1, .cam_rx_ms = 7, .cam_fseq = 5 };
    vision_step(&st, &p, 8);
    if (!st.vision_out.new_sample || st.vision_out.x_px != -20.0f || st.vision_out.t_ms != 7u) return DZ_EFAIL;
    if (st.vision_out.state != (uint8_t)VIS_VALID || st.vision_out.age_ms != 1u) return DZ_EFAIL;
    vision_step(&st, &p, 100);
    if (st.vision_out.new_sample || st.vision_out.state != (uint8_t)VIS_HELD) return DZ_EFAIL;
    vision_step(&st, &p, 400);
    return st.vision_out.state == (uint8_t)VIS_LOST ? DZ_OK : DZ_EFAIL;
}

const subsys_t SUBSYS_VISION = { "vision", PERIOD_MS_VISION, true, vision_init, vision_step, 0, vision_selftest };
