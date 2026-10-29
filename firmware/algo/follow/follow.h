/**
 * @file follow.h
 * @brief 跟车间距控制（纯逻辑）：v_cmd = v_lead + kp·(gap − gap_ref) − kd·(v_self − v_lead)，限幅限加速度。
 *
 * gap = s_lead − s_self（沿路径里程差，两车同一起点同时清零；或测距传感器直接给）。
 * 安全：gap < gap_min → 0（太近，立刻停）；对方数据不新鲜（调用方给 lead_ok=false）→ 按 decel 减速到 0，状态 LINK_LOST；
 *       对方 STOPPED / 中止由调用方给 lead_ok=false 或 v_lead=0 即可。加速受 accel 限，减速受 decel 限（停车不受限：太近时直接 0）。
 * 版本：FOLLOW_VERSION
 */
#ifndef FOLLOW_H
#define FOLLOW_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#define FOLLOW_VERSION "1.0.0"

typedef enum { FOLLOW_OK = 0, FOLLOW_TOO_CLOSE = 1, FOLLOW_LINK_LOST = 2 } follow_state_t;

typedef struct {
    float gap_ref_m, gap_min_m;   /**< 目标间距、最小间距（< 此值立停） */
    float kp, kd;                 /**< 1/s、无量纲 */
    float v_max;                  /**< m/s，不倒车（下限 0） */
    float accel, decel;           /**< m/s²，>0 */
} follow_cfg_t;

typedef struct { follow_cfg_t c; float v; follow_state_t st; } follow_t;

dz_err_t follow_init(follow_t *f, const follow_cfg_t *c);
/** dt_s 控制周期。返回速度指令 m/s。 */
float follow_step(follow_t *f, bool lead_ok, float gap_m, float v_lead, float v_self, float dt_s);
dz_err_t follow_selftest(void);
#endif
