/**
 * @file ball_beam.h
 * @brief 单轴球杆（钢珠-摆杆）控制器：α-β 状态估计 + 超前预测 + 位置→速度→角度串级 + 条件积分。
 *
 * 结构（纯逻辑，不碰硬件，输入像素，输出相对水平的摆杆角 °）：
 *   1) 视觉新样本 → α-β 滤波估计位置 x 与速度 v（Kalata 1984 的 α-β 跟踪器；P2 工程的设计）；
 *   2) 用 v 把位置外推到“现在 + lead_s”，补偿相机曝光/传输/机械延迟（P2：70 ms）；
 *   3) 串级：v_des = clamp(pos_k·e, ±vel_max)，θ = vel_k·(v_des − v) + I + ff（P1 工程的结构）；
 *   4) 积分只在新样本到达且 |e| < i_zone（可选再加 |v| < i_vel，否则按 i_leak 衰减）时累加，误差变号时乘 i_decay（P1 策略），并钳在 ±i_max；
 *   5) 输出限幅 ±angle_max、斜率限制 rate_max（°/s）。
 * 丢样本：age ≤ hold_ms 继续外推；hold_ms < age ≤ timeout_ms 保持上次角度；age > timeout_ms 视为丢球，
 * 斜坡回 0°、清积分，下一个样本重新初始化滤波器。
 * 1.1.0 A/B 选项（cfg 末尾字段，全 0 即原行为）：估计器 α-β/差分低通、串级/单环、静摩擦补偿、静平衡前馈表。
 * 符号约定：输出 θ>0 应使球向 +x 加速；机械方向相反时把 dir 设为 −1。
 * 版本：BALL_BEAM_VERSION
 */
#ifndef BALL_BEAM_H
#define BALL_BEAM_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#define BALL_BEAM_VERSION "1.2.0"
#define BB_BAL_MAX 5u

/** A/B 选项：0 = A（默认，1.0.0 行为），1 = B（回退方案）。 */
typedef enum { BB_EST_ALPHA_BETA = 0, BB_EST_DIFF_LPF = 1 } bb_est_mode_t;
typedef enum { BB_LOOP_CASCADE = 0, BB_LOOP_SINGLE = 1 } bb_loop_mode_t;

typedef struct {
    float alpha, beta;       /**< α-β 增益，0<α≤1，0≤β<2（稳定域 0<β<4−2α） */
    float lead_s;            /**< 超前预测量（秒） */
    float pos_k;             /**< 位置环 (px/s)/px */
    float vel_max;           /**< 期望速度上限 px/s */
    float vel_k;             /**< 速度环 °/(px/s) */
    float ki;                /**< 积分 °/(px·s) */
    float i_zone;            /**< 积分区 px（|e| 小于才积分），<=0 关闭积分 */
    float i_max;             /**< 积分上限 ° */
    float i_decay;           /**< 误差变号时积分乘的系数 0..1 */
    float angle_max;         /**< 输出限幅 ° */
    float rate_max;          /**< 斜率限制 °/s，<=0 不限 */
    uint32_t hold_ms, timeout_ms;
    float dir;               /**< +1 / −1 */
    /* ---- 1.1.0 可选项（全 0 = 1.0.0 行为） ---- */
    uint8_t est_mode;        /**< bb_est_mode_t。B：速度 = 差分经一阶低通（系数 est_lpf），α-β 发散/调不动时用 */
    float   est_lpf;         /**< B 模式速度低通系数 (0,1]；0 视为 0.3 */
    uint8_t loop_mode;       /**< bb_loop_mode_t。B：单环 θ = vel_k·(pos_k·e − v)，不限 v_des（串级调不顺时的回退） */
    float   stic_deg;        /**< 静摩擦补偿角 °（0 关）：球几乎不动(|v|<stic_vel)且 |e|>stic_e 时沿误差方向加 */
    float   stic_vel;        /**< px/s */
    float   stic_e;          /**< px */
    uint8_t bal_n;           /**< 静平衡前馈表点数（0/1 关，2..BB_BAL_MAX 开）：θ0(x) = 球静止在 x 处所需的摆杆角 */
    float   bal_x[BB_BAL_MAX];   /**< px，严格递增 */
    float   bal_deg[BB_BAL_MAX]; /**< °，直接叠加在输出上（不乘 dir），表外按端点保持 */
    /* ---- 1.2.0 可选项：条件积分（全 0 = 1.1.0 行为）。思路参考 nuedc-2026-h-ball-balance（MIT）：
     *      只在误差小且对象几乎静止时积分，否则积分逐拍衰减 —— 防止“还在快速接近目标时”积分先攒满造成超调 ---- */
    float   i_vel;           /**< px/s，>0 时只在 |v| < i_vel 才累加积分（0 关） */
    float   i_leak;          /**< 不满足积分条件时每个新样本积分乘的系数 (0,1)（0 关 = 保持；参考值 31/32） */
} ball_beam_cfg_t;

typedef enum { BB_WAIT = 0, BB_TRACK, BB_HOLD, BB_LOST } ball_beam_state_t;

typedef struct {
    ball_beam_cfg_t cfg;
    bool primed;
    float x, v;              /**< 估计位置 px / 速度 px/s（样本时刻） */
    uint32_t t_sample;
    float integ, e_prev, out;
    bool new_sample;
    ball_beam_state_t state;
} ball_beam_t;

dz_err_t ball_beam_init(ball_beam_t *b, const ball_beam_cfg_t *cfg);
void ball_beam_reset(ball_beam_t *b);
/** 视觉新样本（相对中心的像素，t_ms 为采样时刻，最好是相机给的时间戳换算到本机时钟）。 */
void ball_beam_sample(ball_beam_t *b, float x_px, uint32_t t_ms);
/** 周期调用，返回摆杆角（°，相对水平）。ff_deg 为外部前馈（例如底盘加速度），直接相加。 */
float ball_beam_update(ball_beam_t *b, float setpoint_px, float ff_deg, uint32_t now_ms, float dt_s);
ball_beam_state_t ball_beam_state(const ball_beam_t *b);
/** 静平衡前馈表插值（bal_n<2 返回 0）。 */
float ball_beam_bal_ff(const ball_beam_cfg_t *c, float x_px);
dz_err_t ball_beam_selftest(void);
#endif
