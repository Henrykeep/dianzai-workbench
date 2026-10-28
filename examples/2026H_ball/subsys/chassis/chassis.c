/**
 * 子系统 chassis：底盘轮速闭环，并估计加速度供别的子系统做前馈。
 * 读：io_in, coord   写：chassis_out
 */
#include "project_gen.h"
#include "pid.h"
#include "lpf1.h"

static pid_ctrl_t s_pid;
static float s_prev_rps;
static lpf1_t s_acc_lpf;   /* 编码器速度做差分噪声很大，前馈用的加速度必须滤波 */

static dz_err_t chassis_init(void *state, const void *params)
{
    shared_state_t *st = state; const params_t *p = params;
    pid_cfg_t c = pid_cfg_default(PERIOD_MS_CHASSIS * 1e-3f);
    c.kp = p->chassis_kp; c.ki = p->chassis_ki;
    st->chassis_out = (st_chassis_out_t){0};
    s_prev_rps = 0;
    lpf1_cfg_t lc = { 5.0f, PERIOD_MS_CHASSIS * 1e-3f };
    if (lpf1_init(&s_acc_lpf, &lc) != DZ_OK) return DZ_EINVAL;
    return pid_init(&s_pid, &c);
}

static void chassis_step(void *state, const void *params, uint32_t now_ms)
{
    shared_state_t *st = state; const params_t *p = params; (void)now_ms;
    /* 参数档切换后增益跟随（pid_set_gains 无扰切换） */
    if (s_pid.cfg.kp != p->chassis_kp || s_pid.cfg.ki != p->chassis_ki) pid_set_gains(&s_pid, p->chassis_kp, p->chassis_ki, 0.0f);
    float w = st->io_in.wheel_rps;
    st->chassis_out.accel_rps2 = lpf1_update(&s_acc_lpf, (w - s_prev_rps) / (PERIOD_MS_CHASSIS * 1e-3f));
    s_prev_rps = w;
    st->chassis_out.motor_cmd = pid_update(&s_pid, st->coord.chassis_sp_rps, w);
}

static void chassis_on_mode(void *state, subsys_mode_t mode)
{
    shared_state_t *st = state;
    if (mode != SUBSYS_MODE_RUN) { pid_reset(&s_pid); lpf1_clear(&s_acc_lpf); st->chassis_out.motor_cmd = 0.0f; st->chassis_out.accel_rps2 = 0.0f; }
}

const subsys_t SUBSYS_CHASSIS = { "chassis", PERIOD_MS_CHASSIS, false, chassis_init, chassis_step, chassis_on_mode, 0 };
