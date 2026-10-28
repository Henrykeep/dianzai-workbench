/**
 * 子系统 vision：把 io_in 里的原始像素坐标变成以平台中心为原点的毫米坐标，并判断数据是否新鲜。
 * 读：io_in   写：vision_out
 */
#include "project_gen.h"

static dz_err_t vision_init(void *state, const void *params)
{
    shared_state_t *st = state; (void)params;
    st->vision_out = (st_vision_out_t){0};
    return DZ_OK;
}

static void vision_step(void *state, const void *params, uint32_t now_ms)
{
    shared_state_t *st = state; const params_t *p = params;
    uint32_t age = st->io_in.cam_seq ? now_ms - st->io_in.cam_rx_ms : UINT32_MAX;
    st->vision_out.age_ms = age;
    st->vision_out.valid = st->io_in.cam_seq && st->io_in.cam_found && age <= p->vision_timeout_ms;
    if (st->vision_out.valid) {
        st->vision_out.x_mm = ((float)st->io_in.cam_x_px - p->cam_cx_px) * p->mm_per_px;
        st->vision_out.y_mm = ((float)st->io_in.cam_y_px - p->cam_cy_px) * p->mm_per_px;
    }
}

static dz_err_t vision_selftest(void)
{
    shared_state_t st = {0};
    params_t p = { .mm_per_px = 0.5f, .cam_cx_px = 320, .cam_cy_px = 240, .vision_timeout_ms = 100 };
    st.io_in = (st_io_in_t){ .cam_x_px = 340, .cam_y_px = 240, .cam_found = true, .cam_seq = 1, .cam_rx_ms = 0 };
    vision_step(&st, &p, 50);
    if (!st.vision_out.valid || st.vision_out.x_mm < 9.99f || st.vision_out.x_mm > 10.01f) return DZ_EFAIL;
    vision_step(&st, &p, 500);
    return st.vision_out.valid ? DZ_EFAIL : DZ_OK;
}

const subsys_t SUBSYS_VISION = { "vision", PERIOD_MS_VISION, true, vision_init, vision_step, 0, vision_selftest };
