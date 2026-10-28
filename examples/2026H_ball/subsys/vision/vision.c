/**
 * 子系统 vision：从 io_in 取出“新到达且有效”的视觉样本交给钢珠环。像素坐标已由相机给成相对画面中心。
 * 读：io_in   写：vision_out
 * flags：bit0 有效 才算样本；bit2 标定过期只做提示（不丢弃）。
 */
#include "project_gen.h"

static uint32_t s_last_seq;

static dz_err_t vision_init(void *state, const void *params)
{
    shared_state_t *st = state; (void)params;
    st->vision_out = (st_vision_out_t){0};
    s_last_seq = st->io_in.cam_seq;
    return DZ_OK;
}

static void vision_step(void *state, const void *params, uint32_t now_ms)
{
    shared_state_t *st = state; (void)params; (void)now_ms;
    st->vision_out.new_sample = false;
    if (st->io_in.cam_seq == s_last_seq) return;
    s_last_seq = st->io_in.cam_seq;
    if (!(st->io_in.cam_flags & 0x01u)) return;                 /* 无效帧：不更新，钢珠环靠超时处理 */
    st->vision_out.new_sample = true;
    st->vision_out.x_px = (float)st->io_in.cam_x_px;
    st->vision_out.t_ms = st->io_in.cam_rx_ms;
}

static dz_err_t vision_selftest(void)
{
    shared_state_t st = {0};
    vision_init(&st, 0);
    st.io_in = (st_io_in_t){ .cam_x_px = -20, .cam_flags = 0x09, .cam_seq = 1, .cam_rx_ms = 7 };
    vision_step(&st, 0, 8);
    if (!st.vision_out.new_sample || st.vision_out.x_px != -20.0f || st.vision_out.t_ms != 7u) return DZ_EFAIL;
    vision_step(&st, 0, 9);
    return st.vision_out.new_sample ? DZ_EFAIL : DZ_OK;
}

const subsys_t SUBSYS_VISION = { "vision", PERIOD_MS_VISION, true, vision_init, vision_step, 0, vision_selftest };
