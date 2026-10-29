#include "pid.h"

static bool pid_finite(float x) { return (x == x) && (x - x == 0.0f); }

static float pid_clamp(float x, float lo, float hi)
{
    return x < lo ? lo : (x > hi ? hi : x);
}

static float pid_abs(float x) { return x < 0.0f ? -x : x; }

pid_cfg_t pid_cfg_default(float dt_s)
{
    pid_cfg_t c;
    c.kp = 0.0f; c.ki = 0.0f; c.kd = 0.0f;
    c.dt_s = dt_s;
    c.out_min = -1.0f; c.out_max = 1.0f;
    c.i_min = -1.0f;   c.i_max = 1.0f;
    c.i_sep = 0.0f;
    c.d_tau_s = 0.0f;
    c.out_rate_max = 0.0f;
    c.d_mode = PID_D_ON_MEASUREMENT;
    return c;
}

dz_err_t pid_cfg_check(const pid_cfg_t *c)
{
    if (c == 0) return DZ_EINVAL;
    const float f[] = { c->kp, c->ki, c->kd, c->dt_s, c->out_min, c->out_max,
                        c->i_min, c->i_max, c->i_sep, c->d_tau_s, c->out_rate_max };
    for (unsigned i = 0; i < sizeof f / sizeof f[0]; i++)
        if (!pid_finite(f[i])) return DZ_EINVAL;
    if (c->kp < 0.0f || c->ki < 0.0f || c->kd < 0.0f) return DZ_EINVAL;
    if (c->dt_s <= 0.0f) return DZ_EINVAL;
    if (!(c->out_min < c->out_max)) return DZ_EINVAL;
    if (c->i_min > c->i_max) return DZ_EINVAL;
    if (c->d_tau_s < 0.0f || c->out_rate_max < 0.0f) return DZ_EINVAL;
    if (c->d_mode != PID_D_ON_MEASUREMENT && c->d_mode != PID_D_ON_ERROR) return DZ_EINVAL;
    return DZ_OK;
}

/* 计算滤波后的导数（未乘 kd）。first 时导数为 0，避免启动冲击。 */
static float pid_derivative(const pid_cfg_t *c, bool first, float err, float meas,
                            float prev_err, float prev_meas, float d_filt_prev)
{
    float d_raw;
    if (first) return 0.0f;
    if (c->d_mode == PID_D_ON_MEASUREMENT) d_raw = -(meas - prev_meas) / c->dt_s;
    else                                   d_raw = (err - prev_err) / c->dt_s;
    if (c->d_tau_s > 0.0f) {
        float a = c->dt_s / (c->d_tau_s + c->dt_s);
        return d_filt_prev + a * (d_raw - d_filt_prev);
    }
    return d_raw;
}

static float pid_rate_limit(const pid_cfg_t *c, float target, float prev)
{
    if (c->out_rate_max <= 0.0f) return target;
    float step = c->out_rate_max * c->dt_s;
    return pid_clamp(target, prev - step, prev + step);
}

/* ======================= 位置式 ======================= */

dz_err_t pid_init(pid_ctrl_t *pid, const pid_cfg_t *cfg)
{
    if (pid == 0) return DZ_EINVAL;
    dz_err_t e = pid_cfg_check(cfg);
    if (e != DZ_OK) return e;
    pid->cfg = *cfg;
    pid->ready = true;
    pid_reset(pid);
    return DZ_OK;
}

void pid_reset(pid_ctrl_t *pid)
{
    if (pid == 0) return;
    pid->integ = 0.0f;
    pid->prev_meas = 0.0f;
    pid->prev_err = 0.0f;
    pid->d_filt = 0.0f;
    pid->out = pid_clamp(0.0f, pid->cfg.out_min, pid->cfg.out_max);
    pid->p_term = pid->i_term = pid->d_term = 0.0f;
    pid->nan_count = 0;
    pid->first = true;
}

void pid_reset_to(pid_ctrl_t *pid, float out0)
{
    if (pid == 0 || !pid->ready || !pid_finite(out0)) return;
    pid_reset(pid);
    pid->out = pid_clamp(out0, pid->cfg.out_min, pid->cfg.out_max);
    /* 让积分项承担初始输出，首拍 P=D=0 时输出不跳变 */
    pid->integ = pid_clamp(pid->out, pid->cfg.i_min, pid->cfg.i_max);
}

float pid_update(pid_ctrl_t *pid, float sp, float meas)
{
    if (pid == 0 || !pid->ready) return 0.0f;
    const pid_cfg_t *c = &pid->cfg;
    if (!pid_finite(sp) || !pid_finite(meas)) {
        pid->nan_count++;
        return pid->out;
    }

    float err = sp - meas;
    float p = c->kp * err;

    pid->d_filt = pid_derivative(c, pid->first, err, meas, pid->prev_err,
                                 pid->prev_meas, pid->d_filt);
    float d = c->kd * pid->d_filt;

    /* 积分：分离 + 限幅 */
    float integ_new = pid->integ;
    if (c->i_sep <= 0.0f || pid_abs(err) <= c->i_sep)
        integ_new = pid_clamp(pid->integ + c->ki * err * c->dt_s, c->i_min, c->i_max);

    float u_unsat = p + integ_new + d;
    float u = pid_clamp(u_unsat, c->out_min, c->out_max);

    /* 条件积分：输出已饱和且积分还在往饱和方向走时，冻结积分 */
    bool push_high = (u_unsat > c->out_max) && (integ_new > pid->integ);
    bool push_low  = (u_unsat < c->out_min) && (integ_new < pid->integ);
    if (!(push_high || push_low)) pid->integ = integ_new;
    else u = pid_clamp(p + pid->integ + d, c->out_min, c->out_max);

    u = pid_rate_limit(c, u, pid->out);

    pid->p_term = p;
    pid->i_term = pid->integ;
    pid->d_term = d;
    pid->prev_err = err;
    pid->prev_meas = meas;
    pid->first = false;
    pid->out = u;
    return u;
}

dz_err_t pid_set_gains(pid_ctrl_t *pid, float kp, float ki, float kd)
{
    if (pid == 0 || !pid->ready) return DZ_ESTATE;
    pid_cfg_t c = pid->cfg;
    c.kp = kp; c.ki = ki; c.kd = kd;
    return pid_set_cfg(pid, &c);
}

dz_err_t pid_set_cfg(pid_ctrl_t *pid, const pid_cfg_t *cfg)
{
    if (pid == 0 || !pid->ready) return DZ_ESTATE;
    dz_err_t e = pid_cfg_check(cfg);
    if (e != DZ_OK) return e;
    if (cfg->dt_s != pid->cfg.dt_s) return DZ_EINVAL;
    pid->cfg = *cfg;
    pid->integ = pid_clamp(pid->integ, cfg->i_min, cfg->i_max);
    pid->out = pid_clamp(pid->out, cfg->out_min, cfg->out_max);
    return DZ_OK;
}

float pid_output(const pid_ctrl_t *pid) { return pid ? pid->out : 0.0f; }

bool pid_check_gap(pid_ctrl_t *pid, float actual_dt_s)
{
    if (pid == 0 || !pid->ready) return false;
    if (pid_finite(actual_dt_s) && actual_dt_s > 0.0f && actual_dt_s <= PID_GAP_MAX_S &&
        actual_dt_s <= PID_GAP_FACTOR * pid->cfg.dt_s) return false;
    pid->first = true;          /* 下一拍重新取 prev_meas/prev_err，不求跨间隔的导数 */
    pid->d_filt = 0.0f;
    pid->d_term = 0.0f;
    return true;
}

/* ======================= 增量式 ======================= */

dz_err_t pid_inc_init(pid_inc_t *pid, const pid_cfg_t *cfg)
{
    if (pid == 0) return DZ_EINVAL;
    dz_err_t e = pid_cfg_check(cfg);
    if (e != DZ_OK) return e;
    pid->cfg = *cfg;
    pid->ready = true;
    pid_inc_reset(pid);
    return DZ_OK;
}

void pid_inc_reset(pid_inc_t *pid)
{
    if (pid == 0) return;
    pid->prev_err = pid->prev_meas = 0.0f;
    pid->d_filt = pid->prev_d_filt = 0.0f;
    pid->out = pid_clamp(0.0f, pid->cfg.out_min, pid->cfg.out_max);
    pid->nan_count = 0;
    pid->first = true;
}

float pid_inc_update(pid_inc_t *pid, float sp, float meas)
{
    if (pid == 0 || !pid->ready) return 0.0f;
    const pid_cfg_t *c = &pid->cfg;
    if (!pid_finite(sp) || !pid_finite(meas)) {
        pid->nan_count++;
        return pid->out;
    }
    float err = sp - meas;

    /* 比例增量：首拍没有上一误差，取 0，避免初次调用的跳变 */
    float dp = pid->first ? 0.0f : c->kp * (err - pid->prev_err);

    float di = 0.0f;
    if (c->i_sep <= 0.0f || pid_abs(err) <= c->i_sep) di = c->ki * err * c->dt_s;

    pid->prev_d_filt = pid->d_filt;
    pid->d_filt = pid_derivative(c, pid->first, err, meas, pid->prev_err,
                                 pid->prev_meas, pid->d_filt);
    float dd = c->kd * (pid->d_filt - pid->prev_d_filt);
    if (pid->first) dd = 0.0f;

    float u = pid_clamp(pid->out + dp + di + dd, c->out_min, c->out_max);
    u = pid_rate_limit(c, u, pid->out);

    pid->prev_err = err;
    pid->prev_meas = meas;
    pid->first = false;
    pid->out = u;
    return u;
}

dz_err_t pid_inc_set_gains(pid_inc_t *pid, float kp, float ki, float kd)
{
    if (pid == 0 || !pid->ready) return DZ_ESTATE;
    pid_cfg_t c = pid->cfg;
    c.kp = kp; c.ki = ki; c.kd = kd;
    dz_err_t e = pid_cfg_check(&c);
    if (e != DZ_OK) return e;
    pid->cfg = c;
    return DZ_OK;
}

/* ======================= 串级 ======================= */

dz_err_t pid_cascade_init(pid_cascade_t *c, const pid_cfg_t *outer,
                          const pid_cfg_t *inner, uint16_t outer_div)
{
    if (c == 0 || outer == 0 || inner == 0 || outer_div == 0) return DZ_EINVAL;
    if (pid_cfg_check(outer) != DZ_OK || pid_cfg_check(inner) != DZ_OK) return DZ_EINVAL;
    float expect = inner->dt_s * (float)outer_div;
    if (pid_abs(outer->dt_s - expect) > 1e-4f * expect) return DZ_EINVAL;
    pid_ctrl_t o, i;
    if (pid_init(&o, outer) != DZ_OK || pid_init(&i, inner) != DZ_OK) return DZ_EINVAL;
    c->outer = o;
    c->inner = i;
    c->outer_div = outer_div;
    c->tick = 0;
    c->inner_sp = 0.0f;
    c->ready = true;
    return DZ_OK;
}

float pid_cascade_update(pid_cascade_t *c, float sp, float meas_outer, float meas_inner)
{
    if (c == 0 || !c->ready) return 0.0f;
    if (c->tick == 0) c->inner_sp = pid_update(&c->outer, sp, meas_outer);
    c->tick = (uint16_t)((c->tick + 1u) % c->outer_div);
    return pid_update(&c->inner, c->inner_sp, meas_inner);
}

float pid_cascade_update_inner_only(pid_cascade_t *c, float inner_sp, float meas_inner)
{
    if (c == 0 || !c->ready) return 0.0f;
    pid_reset(&c->outer);
    c->tick = 0;
    c->inner_sp = inner_sp;
    return pid_update(&c->inner, inner_sp, meas_inner);
}

void pid_cascade_reset(pid_cascade_t *c)
{
    if (c == 0 || !c->ready) return;
    pid_reset(&c->outer);
    pid_reset(&c->inner);
    c->tick = 0;
    c->inner_sp = 0.0f;
}

/* ======================= 自检 ======================= */

static bool near(float a, float b, float tol) { float d = a - b; return d < tol && d > -tol; }

dz_err_t pid_selftest(void)
{
    {   /* dt 异常：正常间隔不动，超长间隔清微分、保留积分 */
        pid_cfg_t g = pid_cfg_default(0.01f);
        pid_ctrl_t q;
        g.kd = 1.0f; g.ki = 1.0f;
        if (pid_init(&q, &g) != DZ_OK) return DZ_EFAIL;
        (void)pid_update(&q, 1.0f, 0.0f); (void)pid_update(&q, 1.0f, 0.1f);
        if (pid_check_gap(&q, 0.01f)) return DZ_EFAIL;
        float i0 = q.integ;
        if (!pid_check_gap(&q, 0.8f) || !q.first || q.d_filt != 0.0f || q.integ != i0) return DZ_EFAIL;
        if (!pid_check_gap(&q, -1.0f)) return DZ_EFAIL;
    }
    pid_ctrl_t p;
    pid_cfg_t c = pid_cfg_default(0.01f);

    /* 非法配置被拒绝 */
    c.dt_s = 0.0f;
    if (pid_init(&p, &c) != DZ_EINVAL) return DZ_EFAIL;
    c = pid_cfg_default(0.01f);
    c.kp = -1.0f;
    if (pid_init(&p, &c) != DZ_EINVAL) return DZ_EFAIL;

    /* 纯 P */
    c = pid_cfg_default(0.01f);
    c.kp = 0.5f;
    if (pid_init(&p, &c) != DZ_OK) return DZ_EFAIL;
    if (!near(pid_update(&p, 1.0f, 0.0f), 0.5f, 1e-6f)) return DZ_EFAIL;

    /* 输出限幅 */
    c.kp = 100.0f;
    pid_init(&p, &c);
    if (!near(pid_update(&p, 1.0f, 0.0f), 1.0f, 1e-6f)) return DZ_EFAIL;

    /* 积分限幅 */
    c = pid_cfg_default(0.01f);
    c.ki = 100.0f; c.i_max = 0.3f; c.i_min = -0.3f;
    pid_init(&p, &c);
    for (int k = 0; k < 100; k++) pid_update(&p, 1.0f, 0.0f);
    if (!near(p.integ, 0.3f, 1e-6f)) return DZ_EFAIL;

    /* 微分先行：设定值阶跃不产生 D 冲击 */
    c = pid_cfg_default(0.01f);
    c.kd = 1.0f;
    pid_init(&p, &c);
    pid_update(&p, 0.0f, 0.0f);
    if (!near(pid_update(&p, 1.0f, 0.0f), 0.0f, 1e-6f)) return DZ_EFAIL;

    /* NaN 输入保持输出 */
    c = pid_cfg_default(0.01f);
    c.kp = 0.5f;
    pid_init(&p, &c);
    float o = pid_update(&p, 1.0f, 0.0f);
    float nan = 0.0f / 0.0f;
    if (!near(pid_update(&p, nan, 0.0f), o, 1e-6f) || p.nan_count != 1) return DZ_EFAIL;

    /* 串级 dt 不匹配被拒绝 */
    pid_cascade_t cc;
    pid_cfg_t ci = pid_cfg_default(0.001f), co = pid_cfg_default(0.01f);
    if (pid_cascade_init(&cc, &co, &ci, 5) != DZ_EINVAL) return DZ_EFAIL;
    if (pid_cascade_init(&cc, &co, &ci, 10) != DZ_OK) return DZ_EFAIL;
    return DZ_OK;
}
