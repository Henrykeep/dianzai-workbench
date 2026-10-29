/**
 * @file line_obs.h
 * @brief 丢线观测与找线恢复（纯逻辑，不碰硬件）。输入每拍“看没看到线 + 线位置 + 是否路口”，输出状态和找线方向。
 *
 * 状态：TRACK 正常循迹 → 连续 lost_confirm 拍没看到线 → LOST（找线：朝最近 dir_frames 拍线位置的平均方向转）
 *       → 连续 reacq_frames 拍又看到线 → TRACK；LOST 超过 lost_timeout_ms → FAIL（锁存，调用方安全停车，line_obs_reset 解除）。
 *       WIDE = 路口/横线（cross），不算丢线、不更新方向。
 * 思路来自 DS-land-and-air（2026 电赛 D 题）car/Hardware/app_line_observer.c 的“全白确认若干拍”与联调矩阵里的
 * LOST_HOLD（按最近 4 帧方向搜线、10 周期稳定重获、12 s 超时停车）。Source: github.com/2026-nuedc-d-land-air/DS-land-and-air@0cec55c
 * （用户确认可直接用，见 docs/参考来源.md）；原实现绑 F103 灰度掩码和 JY901，这里抽成与传感器无关的纯逻辑。
 * 版本：LINE_OBS_VERSION
 */
#ifndef LINE_OBS_H
#define LINE_OBS_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#define LINE_OBS_VERSION "1.0.0"
#define LINE_OBS_DIR_MAX 16u

typedef enum { LINE_OBS_TRACK = 0, LINE_OBS_WIDE = 1, LINE_OBS_LOST = 2, LINE_OBS_FAIL = 3 } line_obs_state_t;

typedef struct {
    uint8_t  lost_confirm;     /**< 连续几拍没线才算丢（滤掉反光/接插件抖动），DS 用 3 */
    uint8_t  dir_frames;       /**< 找线方向取最近几拍线位置的平均（1..16），DS 用 4 */
    uint8_t  reacq_frames;     /**< 连续几拍看到线才算找回，DS 用 10 */
    uint32_t lost_timeout_ms;  /**< 丢线多久判失败停车；0 = 不超时。DS 用 12000 */
    float    center_band;      /**< |平均位置| 小于此值视为“正前方丢的”：方向给 0（调用方直行/按任务决定） */
} line_obs_cfg_t;

typedef struct {
    line_obs_cfg_t c;
    line_obs_state_t st;
    float hist[LINE_OBS_DIR_MAX]; uint8_t hn, hi;
    uint8_t miss, seen;
    bool just;                 /**< 本拍刚进 LOST */
    uint32_t t_lost;
    int8_t dir;                /**< 找线方向：-1 左 / +1 右 / 0 不确定（左负右正，与 line_sensor 一致） */
    uint32_t lost_count;       /**< 累计丢线次数（给黑匣子/遥测） */
} line_obs_t;

line_obs_cfg_t line_obs_cfg_default(void);
/** 参数非法（dir_frames 0 或 >16、lost_confirm/reacq_frames 为 0、center_band 负/NaN）→ DZ_EINVAL。 */
dz_err_t line_obs_init(line_obs_t *o, const line_obs_cfg_t *c);
/** 每拍调一次。pos 只在 seen 时有意义（非有限值按没看到）。返回新状态。 */
line_obs_state_t line_obs_update(line_obs_t *o, bool seen, float pos, bool cross, uint32_t now_ms);
/** 进 LOST 那一拍返回 true（调用方记黑匣子 BB_EV_LINE_LOST 用）。 */
bool line_obs_just_lost(const line_obs_t *o);
int8_t line_obs_dir(const line_obs_t *o);
void line_obs_reset(line_obs_t *o);
dz_err_t line_obs_selftest(void);
#endif
