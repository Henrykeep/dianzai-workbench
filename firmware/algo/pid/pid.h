/**
 * @file pid.h
 * @brief PID 控制器：位置式、增量式、串级。纯 C，无硬件依赖，可在 PC 上单测。
 *
 * 版本：PID_VERSION（与同目录 VERSION 文件一致）
 *
 * 功能一览（均可通过配置开关）：
 *  - 积分限幅（i_min/i_max，单位与输出相同）+ 饱和时停止积分（条件积分抗饱和）
 *  - 积分分离（|误差| 大于阈值时不积分，常用于大范围移动的球类系统）
 *  - 微分先行（对测量值求导，设定值阶跃时没有"微分冲击"）或对误差求导
 *  - 微分一阶低通（d_tau_s 时间常数），抑制视觉坐标等噪声被 D 放大
 *  - 输出限幅（out_min/out_max）与输出变化率限制（out_rate_max，单位/秒）
 *  - 改增益无扰动（积分项按"贡献量"存储，改 ki 不会让输出跳变）
 *  - NaN/Inf 输入被拒绝：保持上一次输出并计数
 *
 * 约定：kp/ki/kd 必须 >= 0。反作用系统（加大输出反而让测量值变小）
 * 请在应用层把测量值或输出取负，而不是填负增益——这样抗饱和逻辑始终正确。
 */
#ifndef PID_H
#define PID_H

#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"

#define PID_VERSION "1.0.0"

typedef enum {
    PID_D_ON_MEASUREMENT = 0, /**< 微分先行（默认，推荐） */
    PID_D_ON_ERROR       = 1  /**< 对误差求导（跟踪快速变化的设定值时可能更好） */
} pid_d_mode_t;

/** 配置。用 pid_cfg_default() 得到安全默认值再改需要的字段。 */
typedef struct {
    float kp, ki, kd;     /**< 增益，>= 0 */
    float dt_s;           /**< 控制周期（秒），> 0，必须与实际调用周期一致 */
    float out_min;        /**< 输出下限 */
    float out_max;        /**< 输出上限，> out_min */
    float i_min;          /**< 积分项贡献下限（输出单位） */
    float i_max;          /**< 积分项贡献上限（输出单位） */
    float i_sep;          /**< 积分分离阈值：|err| > i_sep 时不积分；<= 0 关闭 */
    float d_tau_s;        /**< 微分低通时间常数（秒）；0 关闭 */
    float out_rate_max;   /**< 输出最大变化率（单位/秒）；0 关闭 */
    pid_d_mode_t d_mode;
} pid_cfg_t;

/** 位置式 PID 句柄。字段私有，只读调试可用 pid_debug_t。 */
typedef struct {
    pid_cfg_t cfg;
    float integ;          /**< 积分项贡献（已乘 ki） */
    float prev_meas;
    float prev_err;
    float d_filt;         /**< 滤波后的导数（未乘 kd） */
    float out;
    float p_term, i_term, d_term; /**< 最近一次各项，便于遥测 */
    uint32_t nan_count;
    bool  first;
    bool  ready;          /**< init 成功后为 true */
} pid_ctrl_t;

/** 增量式 PID 句柄。u[k] = u[k-1] + Δu，天然不积分饱和。i_min/i_max 不使用。 */
typedef struct {
    pid_cfg_t cfg;
    float prev_err;
    float prev_meas;
    float d_filt;
    float prev_d_filt;
    float out;
    uint32_t nan_count;
    bool  first;
    bool  ready;
} pid_inc_t;

/** 串级 PID：外环输出作为内环设定值。外环每 outer_div 个内环周期运行一次。 */
typedef struct {
    pid_ctrl_t outer;
    pid_ctrl_t inner;
    uint16_t   outer_div;
    uint16_t   tick;
    float      inner_sp;
    bool       ready;
} pid_cascade_t;

/** 填充安全默认值：增益 0，输出 ±1，积分 ±1，其余功能关闭。 */
pid_cfg_t pid_cfg_default(float dt_s);

/** 检查配置是否合法，合法返回 DZ_OK。 */
dz_err_t pid_cfg_check(const pid_cfg_t *cfg);

/* ---------------- 位置式 ---------------- */
dz_err_t pid_init(pid_ctrl_t *pid, const pid_cfg_t *cfg);
/** 计算一步。未初始化或 pid 为 NULL 时返回 0。 */
float    pid_update(pid_ctrl_t *pid, float setpoint, float measurement);
/** 清空状态，输出回到 0。 */
void     pid_reset(pid_ctrl_t *pid);
/** 无扰切换：把内部状态设置为输出 out0（例如从手动切到自动时）。 */
void     pid_reset_to(pid_ctrl_t *pid, float out0);
/** 运行中改增益（无扰动）。非法返回 DZ_EINVAL 且不改动。 */
dz_err_t pid_set_gains(pid_ctrl_t *pid, float kp, float ki, float kd);
/** 运行中整体替换配置（dt 不可改，改 dt 请重新 init）。 */
dz_err_t pid_set_cfg(pid_ctrl_t *pid, const pid_cfg_t *cfg);
float    pid_output(const pid_ctrl_t *pid);

/* ---------------- 增量式 ---------------- */
dz_err_t pid_inc_init(pid_inc_t *pid, const pid_cfg_t *cfg);
float    pid_inc_update(pid_inc_t *pid, float setpoint, float measurement);
void     pid_inc_reset(pid_inc_t *pid);
dz_err_t pid_inc_set_gains(pid_inc_t *pid, float kp, float ki, float kd);

/* ---------------- 串级 ---------------- */
/**
 * outer->dt_s 必须等于 inner->dt_s * outer_div（相对误差 1e-4 以内），否则 DZ_EINVAL。
 * 这条检查专门防止"外环周期写错导致积分/微分系数全错"的隐蔽问题。
 */
dz_err_t pid_cascade_init(pid_cascade_t *c, const pid_cfg_t *outer,
                          const pid_cfg_t *inner, uint16_t outer_div);
/** 以内环周期调用。返回内环输出（执行器指令）。 */
float    pid_cascade_update(pid_cascade_t *c, float setpoint,
                            float meas_outer, float meas_inner);
/** 只跑内环（调参时"先内后外"用），外环状态被清空。 */
float    pid_cascade_update_inner_only(pid_cascade_t *c, float inner_setpoint,
                                       float meas_inner);
void     pid_cascade_reset(pid_cascade_t *c);

/** 模块自检：运行内置用例，全部通过返回 DZ_OK，否则 DZ_EFAIL。 */
dz_err_t pid_selftest(void);

#endif /* PID_H */
