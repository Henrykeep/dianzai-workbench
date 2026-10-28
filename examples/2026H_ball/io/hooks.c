/**
 * 本题的协调钩子：每个测试项给子系统下发什么目标。只写 coord 段。
 */
#include "project_gen.h"
#include "hooks.h"

static void pre_step(void *state, const coord_test_t *t, const void *params, uint32_t tin)
{
    shared_state_t *st = state; (void)params;
    st->coord.test_id = t->id;
    st->coord.ball_sp_px = io_host_ball_sp_px();           /* 默认 0 = 画面中心（相机已对准摆杆中点）；上位机可改 */
    switch (t->id) {
    case 2:  /* 示例：底盘 2 秒线性加速到 0.5 m/s 后保持（真实速度，P1 的“m/s”有 3 倍单位 bug，见 docs/12） */
        st->coord.chassis_mps = tin < 2000u ? 0.5f * (float)tin / 2000.0f : 0.5f;
        break;
    default:
        st->coord.chassis_mps = 0.0f;
        break;
    }
}

const coord_hooks_t g_project_hooks = { pre_step, 0, 0 };
