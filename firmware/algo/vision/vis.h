/**
 * @file vis.h
 * @brief 视觉样本链路状态 + 像素→物理量标定。纯 C，无硬件依赖。
 *
 * vis_link：每收到一帧调用 vis_link_feed()，控制周期里调用 vis_link_poll()。
 *   状态  VIS_VALID  最近 hold_ms 内收到过有效帧；
 *         VIS_HELD   超过 hold_ms 没有新的有效帧，但还没超过 lost_ms（控制环应保持输出或用预测值）；
 *         VIS_LOST   超过 lost_ms，或者从未收到（控制环应进入安全动作）。
 *   时效  age_ms = now − 最近一次有效帧的接收时刻。
 *   延迟  相机时间戳和 MCU 时钟没有同步，绝对延迟测不出来。这里跟踪 (rx_ms − cam_ms) 在窗口内的最小值，
 *         lat_jitter_ms = 当前差值 − 最小值，表示“比最快那一帧慢了多少”。绝对延迟要用 host/python/dzlink/latency.py 闪灯法测。
 *   序号  seq 是 8 位回绕的，跳号累加到 drops。
 *
 * vis_calib：2..VIS_CALIB_MAX 个 (px, 物理量) 标定点做分段线性插值，px 必须严格递增。
 *   在中心两侧各标两点以上（共 ≥4 点）时，左右两侧斜率各自独立，可以吸收镜头畸变和相机没装正的问题。
 *   超出标定范围时按最外侧那一段的斜率外推，并置 out_of_range。
 *
 * 版本：VIS_VERSION（与同目录 VERSION 一致）
 */
#ifndef VIS_H
#define VIS_H

#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"

#define VIS_VERSION "1.1.0"
#define VIS_CALIB_MAX 9u

typedef enum { VIS_LOST = 0, VIS_HELD = 1, VIS_VALID = 2 } vis_state_t;

typedef struct {
    uint32_t hold_ms;      /**< 超过它进入 HELD，例 3 帧周期 */
    uint32_t lost_ms;      /**< 超过它进入 LOST，> hold_ms */
    uint32_t lat_win;      /**< 最小延迟窗口（帧数），例 200；0 = 不限 */
} vis_link_cfg_t;

typedef struct {
    vis_link_cfg_t cfg;
    bool     have, have_seq;
    uint8_t  last_seq;
    uint32_t last_rx_ms, last_cam_ms;
    float    x;                 /**< 最近有效样本 */
    uint32_t drops, frames, invalid;
    int32_t  off_min, off_min_next;   /**< (rx − cam) 的窗口最小值：双缓冲滚动 */
    uint32_t win_n;
    int32_t  lat_jitter_ms;
} vis_link_t;

dz_err_t    vis_link_init(vis_link_t *l, const vis_link_cfg_t *cfg);
/** 一帧到达。valid=false 的帧只计数、更新序号，不刷新时效。 */
void        vis_link_feed(vis_link_t *l, uint8_t seq, uint32_t cam_ms, uint32_t rx_ms, bool valid, float x);
vis_state_t vis_link_poll(const vis_link_t *l, uint32_t now_ms);
uint32_t    vis_link_age_ms(const vis_link_t *l, uint32_t now_ms);   /**< 从未收到返回 UINT32_MAX */
const char *vis_state_name(vis_state_t s);

typedef struct {
    uint8_t n;
    float px[VIS_CALIB_MAX];
    float val[VIS_CALIB_MAX];
} vis_calib_t;

/** px 必须严格递增、2 ≤ n ≤ VIS_CALIB_MAX、全部有限，否则 DZ_EINVAL。 */
dz_err_t vis_calib_init(vis_calib_t *c, const float *px, const float *val, uint8_t n);
float    vis_calib_apply(const vis_calib_t *c, float px, bool *out_of_range);

/* ---------------- 平面五点标定（1.1.0） ----------------
 * 相机斜看一个平面（屏幕、靶纸、地面）时，像素→平面坐标是透视变换（单应），分段线性做不对。
 * 用平面上 4 个已知点（通常是四个角）求单应矩阵 H，第 5 个已知点（通常是中心）只用来验收：
 * 把它的像素坐标代进去，和真实坐标的距离 = check_err，超过你的容差说明点错了 / 相机动了 / 镜头畸变太大。
 * 4 个点要求任意 3 点不共线（实际是凸四边形、按顺序给），否则 DZ_EINVAL。
 * 反向（平面→像素）也一起算好：激光打到屏幕某点、云台要转到像素目标时用。 */
typedef struct {
    float h[9];        /**< 像素 → 平面，行主序，h[8] = 1 */
    float hi[9];       /**< 平面 → 像素 */
    float check_err;   /**< 第 5 点的验收误差（平面单位）；没给第 5 点时为 -1 */
} vis_plane_t;

/** px/py：4 个点的像素坐标；wx/wy：对应平面坐标；chk 为 NULL 表示不验收，否则 chk = {px, py, wx, wy}。 */
dz_err_t vis_plane_init(vis_plane_t *p, const float px[4], const float py[4],
                        const float wx[4], const float wy[4], const float chk[4]);
/** 像素 → 平面。点在相机地平线外（分母≈0）返回 DZ_EINVAL。 */
dz_err_t vis_plane_to_world(const vis_plane_t *p, float u, float v, float *x, float *y);
/** 平面 → 像素。 */
dz_err_t vis_plane_to_pixel(const vis_plane_t *p, float x, float y, float *u, float *v);

dz_err_t vis_selftest(void);

#endif /* VIS_H */
