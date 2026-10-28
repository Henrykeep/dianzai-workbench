/**
 * 子系统 chassis：两轮线速度闭环（同一目标，直行），并估计底盘加速度给钢珠环做前馈。
 * 读：io_in, coord   写：chassis_out
 * 循迹转向不在本例范围（P1/P2 的灰度循迹见 docs/12，需要时再加 track 子系统）。
 */
#include "project_gen.h"
#include "pid.h"
#include "lpf1.h"

static pid_ctrl_t s_a, s_b;
static float s_prev;
static lpf1_t s_acc;

static dz_err_t chassis_init(void *state, const void *params)
{
    shared_state_t *st = state; const params_t *p = params;
    pid_cfg_t c = pid_cfg_default(PERIOD_MS_CHASSIS * 1e-3f);
    lpf1_cfg_t lc = { 5.0f, PERIOD_MS_CHASSIS * 1e-3f };
    dz_err_t e;
    c.kp = p->chassis_kp; c.ki = p->chassis_ki;
    st->chassis_out = (st_chassis_out_t){0};
    s_prev = 0.0f;
    if (lpf1_init(&s_acc, &lc) != DZ_OK) return DZ_EINVAL;
    if ((e = pid_init(&s_a, &c)) != DZ_OK) return e;
    return pid_init(&s_b, &c);
}

static void chassis_step(void *state, const void *params, uint32_t now_ms)
{
    shared_state_t *st = state; const params_t *p = params; (void)now_ms;
    float v;
    if (s_a.cfg.kp != p->chassis_kp || s_a.cfg.ki != p->chassis_ki) {
        pid_set_gains(&s_a, p->chassis_kp, p->chassis_ki, 0.0f); pid_set_gains(&s_b, p->chassis_kp, p->chassis_ki, 0.0f);
    }
    v = 0.5f * (st->io_in.wheel_a_mps + st->io_in.wheel_b_mps);
    st->chassis_out.accel_mps2 = lpf1_update(&s_acc, (v - s_prev) / (PERIOD_MS_CHASSIS * 1e-3f));
    s_prev = v;
    st->chassis_out.cmd_a = pid_update(&s_a, st->coord.chassis_mps, st->io_in.wheel_a_mps);
    st->chassis_out.cmd_b = pid_update(&s_b, st->coord.chassis_mps, st->io_in.wheel_b_mps);
}

static void chassis_on_mode(void *state, subsys_mode_t mode)
{
    shared_state_t *st = state;
    if (mode != SUBSYS_MODE_RUN) {
        pid_reset(&s_a); pid_reset(&s_b); lpf1_clear(&s_acc);
        st->chassis_out = (st_chassis_out_t){0};
    }
}

const subsys_t SUBSYS_CHASSIS = { "chassis", PERIOD_MS_CHASSIS, false, chassis_init, chassis_step, chassis_on_mode, 0 };
