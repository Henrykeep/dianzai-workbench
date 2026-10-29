#include "lpf1.h"

/* 不依赖 math.h，避免在部分嵌入式库下引入额外代码；
 * 注意：不要用 -ffast-math / -ffinite-math-only 编译，否则 NaN 检测会被优化掉。 */
static bool lpf1_finite(float x)
{
    return (x == x) && (x - x == 0.0f);
}

#define LPF1_TWO_PI 6.28318530718f

dz_err_t lpf1_init(lpf1_t *f, const lpf1_cfg_t *cfg)
{
    if (f == 0 || cfg == 0) return DZ_EINVAL;
    if (!lpf1_finite(cfg->cutoff_hz) || !lpf1_finite(cfg->dt_s)) return DZ_EINVAL;
    if (cfg->cutoff_hz <= 0.0f || cfg->dt_s <= 0.0f) return DZ_EINVAL;
    float rc = 1.0f / (LPF1_TWO_PI * cfg->cutoff_hz);
    return lpf1_init_alpha(f, cfg->dt_s / (cfg->dt_s + rc));
}

dz_err_t lpf1_init_alpha(lpf1_t *f, float alpha)
{
    if (f == 0 || !lpf1_finite(alpha) || alpha <= 0.0f || alpha > 1.0f) return DZ_EINVAL;
    f->alpha = alpha;
    f->y = 0.0f;
    f->primed = false;
    return DZ_OK;
}

bool lpf1_check_gap(lpf1_t *f, float actual_dt_s, float max_dt_s)
{
    if (f == 0) return false;
    if (lpf1_finite(actual_dt_s) && actual_dt_s > 0.0f && actual_dt_s <= max_dt_s) return false;
    f->primed = false;
    return true;
}

float lpf1_update(lpf1_t *f, float x)
{
    if (f == 0) return 0.0f;
    if (!lpf1_finite(x)) return f->y;
    if (!f->primed) {
        f->y = x;
        f->primed = true;
    } else {
        f->y += f->alpha * (x - f->y);
    }
    return f->y;
}

void lpf1_reset(lpf1_t *f, float y0)
{
    if (f == 0 || !lpf1_finite(y0)) return;
    f->y = y0;
    f->primed = true;
}

void lpf1_clear(lpf1_t *f)
{
    if (f == 0) return;
    f->y = 0.0f;
    f->primed = false;
}

float lpf1_value(const lpf1_t *f)
{
    return f ? f->y : 0.0f;
}

static bool near(float a, float b, float tol) { float d = a - b; return d < tol && d > -tol; }

dz_err_t lpf1_selftest(void)
{
    lpf1_t f;
    lpf1_cfg_t bad = { 0.0f, 0.001f };
    if (lpf1_init(&f, &bad) != DZ_EINVAL) return DZ_EFAIL;
    if (lpf1_init_alpha(&f, 0.5f) != DZ_OK) return DZ_EFAIL;
    if (!near(lpf1_update(&f, 2.0f), 2.0f, 1e-6f)) return DZ_EFAIL;   /* 首样本直通 */
    if (!near(lpf1_update(&f, 4.0f), 3.0f, 1e-6f)) return DZ_EFAIL;   /* 2 + 0.5*(4-2) */
    if (lpf1_check_gap(&f, 0.01f, 0.05f) || !lpf1_check_gap(&f, 1.0f, 0.05f)) return DZ_EFAIL;
    if (!near(lpf1_update(&f, 9.0f), 9.0f, 1e-6f)) return DZ_EFAIL;   /* 间隔过长：直通重起 */
    float nan = 0.0f / 0.0f;
    if (!near(lpf1_update(&f, nan), 9.0f, 1e-6f)) return DZ_EFAIL;    /* NaN 被丢弃 */
    /* 阶跃足够多步后收敛 */
    for (int i = 0; i < 100; i++) lpf1_update(&f, 10.0f);
    if (!near(lpf1_value(&f), 10.0f, 1e-3f)) return DZ_EFAIL;
    return DZ_OK;
}
