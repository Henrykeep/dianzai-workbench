/**
 * @file lpf1.h
 * @brief 一阶低通滤波（指数平滑）。纯 C，无硬件依赖。
 *
 *   y[k] = y[k-1] + alpha * (x[k] - y[k-1])
 *   alpha = dt / (dt + RC),  RC = 1 / (2*pi*fc)
 *
 * 版本：LPF1_VERSION（与同目录 VERSION 文件一致，tools/check_deps.py 会核对）
 */
#ifndef LPF1_H
#define LPF1_H

#include <stdbool.h>
#include "dz_err.h"

#define LPF1_VERSION "1.0.0"

typedef struct {
    float cutoff_hz;  /**< 截止频率，> 0 */
    float dt_s;       /**< 采样周期（秒），> 0 */
} lpf1_cfg_t;

/** 句柄。字段视为私有，只通过函数访问。 */
typedef struct {
    float alpha;
    float y;
    bool  primed;     /**< 是否已用第一个样本初始化输出 */
} lpf1_t;

/** 按截止频率初始化。参数非法（<=0、NaN、空指针）返回 DZ_EINVAL，句柄不变。 */
dz_err_t lpf1_init(lpf1_t *f, const lpf1_cfg_t *cfg);

/** 直接给定 alpha 初始化，要求 0 < alpha <= 1（alpha = 1 即不滤波）。 */
dz_err_t lpf1_init_alpha(lpf1_t *f, float alpha);

/**
 * 输入一个样本，返回滤波输出。
 *  - 第一个样本直接作为输出（避免从 0 爬升的启动瞬态）。
 *  - 输入为 NaN/Inf 时丢弃该样本，返回上一次输出。
 *  - f 为 NULL 时返回 0。
 */
float lpf1_update(lpf1_t *f, float x);

/** 把输出强制设为 y0，下一样本从 y0 开始平滑。 */
void lpf1_reset(lpf1_t *f, float y0);

/** 清除状态，下一个样本重新作为初值。 */
void lpf1_clear(lpf1_t *f);

/** 当前输出。 */
float lpf1_value(const lpf1_t *f);

/** 模块自检：运行内置用例，全部通过返回 DZ_OK，否则 DZ_EFAIL。可在目标板上调用。 */
dz_err_t lpf1_selftest(void);

#endif /* LPF1_H */
