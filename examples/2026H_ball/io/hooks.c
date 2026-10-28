/**
 * 本题的协调钩子：每个测试项给子系统下发什么目标。状态机本身在 firmware/framework/coord，不改。
 * 只写 coord 段（coord 是该段唯一写者）。
 */
#include "project_gen.h"
#include "hooks.h"

static void pre_step(void *state, const coord_test_t *t, const void *params, uint32_t tin)
{
    shared_state_t *st = state; (void)params;
    st->coord.test_id = t->id;
    st->coord.ball_sp_x_mm = 0.0f;
    st->coord.ball_sp_y_mm = 0.0f;
    switch (t->id) {
    case 2:  /* 示例：底盘 2 秒加速到 1.5 转/秒，之后保持 */
        st->coord.chassis_sp_rps = tin < 2000u ? 1.5f * (float)tin / 2000.0f : 1.5f;
        break;
    default:
        st->coord.chassis_sp_rps = 0.0f;
        break;
    }
}

const coord_hooks_t g_project_hooks = { pre_step, 0, 0 };
