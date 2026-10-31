/**
 * @file dzstep.h
 * @brief dzctl 0.13.0 阶跃实验（#38 Agent 自动迭代的板端指标）+ 参数 CRC32。
 *
 * 板上按遥测节拍逐个样本在线算指标（不存曲线），实验结束发一帧 step_result（DATA id=DZSTEP_ID，len=DZSTEP_RESULT_LEN）。
 * 仿真板（host-sim）与真板是同一份代码。线上格式、口径见 firmware/proto/dzctl/README.md「0.13.0」。
 *
 * 口径（样本 = 实验窗口 [t0, t0+dur_ms] 内每一帧遥测，t 取遥测 t_ms）：
 *   y0 = 第一个样本的测量值；A = sp − y0（阶跃幅度）；e = sp − y。
 *   metric_mode：|A| < max(0.01·range, abs_tol) → abs（绝对口径），否则 rel。
 *   rel：r = (y − y0)/A；overshoot_pct = max(0, max r − 1)·100；rise_ms = t(首个 r≥0.9) − t(首个 r≥0.1)；
 *        band = 0.02·|A|；ss_err_pct = 最后 20% 窗口（5·(t−t0) ≥ 4·dur）的 mean|e| / |A| · 100。
 *   abs：band = abs_tol；overshoot_pct 字段 = max|e|（物理单位，非 %）；ss_err_pct 字段 = 最后 20% 的 mean|e|（物理单位）；rise_ms = 0xFFFFFFFF。
 *   settle_ms：最后一个 |e| > band 的样本之后那个样本的 t − t0；全程都在带内 = 0；最后一个样本仍在带外 = 0xFFFFFFFF。
 *   u_sat_ratio：|u| ≥ 0.99·u_max 的样本占比；应用不提供 u 时 = −1。
 *   peak_abs_err：全部样本 max|e|（含阶跃那一刻，= |A| 起）。
 */
#ifndef DZSTEP_H
#define DZSTEP_H

#include <stdbool.h>
#include <stdint.h>
#include "dzframe.h"
#include "dzctl.h"

#define DZSTEP_PROTO       1u
#define DZSTEP_ID          0x7Bu     /**< DATA：上位机开始/停止阶跃；板回 ack（len 4）与 step_result（len 56） */
#define DZSTEP_REJECT_ID   0x7Au     /**< DATA：板 → 上位机 param_reject */
#define DZSTEP_START_LEN   12u
#define DZSTEP_ACK_LEN     4u
#define DZSTEP_RESULT_LEN  56u
#define DZSTEP_NONE        0xFFFFFFFFu
#define DZSTEP_DUR_MIN_MS  200u
#define DZSTEP_DUR_MAX_MS  30000u

/** 开始应答 status */
enum { DZSTEP_ST_STARTED = 0, DZSTEP_ST_BAD_ARG = 1, DZSTEP_ST_ESTOP = 2, DZSTEP_ST_BUSY = 3,
       DZSTEP_ST_UNSUPPORTED = 4, DZSTEP_ST_OFFLINE = 5 };
/** abort_cause：1..9 = dzctl_estop_cause_t（急停/故障/限位）；0x80 起为板端自定义 */
#define DZSTEP_AB_HOST_STOP 0x80u    /**< 上位机发停止（len=0）或实验中途又发了设定值 DATA id=1 */
/** param_reject reason */
enum { DZSTEP_REJ_RANGE = 1, DZSTEP_REJ_TYPE = 2, DZSTEP_REJ_STATE = 3, DZSTEP_REJ_STEP = 4 };
/** PARAM_ACK 新增 status：5 = 拒绝（不写入；ack 里 f32 = 原值），随后补一帧 param_reject 说明原因 */
#define DZCTL_REJECTED 5u

/** 每个阶跃通道的编译期配置（gen_link.py 从 app.yaml link.step 生成 g_link_step[]） */
typedef struct {
    uint8_t sp_idx;          /**< 设定值槽位（link_app 的 L.sp[]；由 link.yaml step[].sp 声明） */
    float range;             /**< 该量的量程（判 abs 口径：|A| < 1% 量程） */
    float abs_tol;           /**< 绝对容差（物理单位） */
    float u_max;             /**< 饱和判定的输出上限；u_max_param ≥ 0 时用该参数的当前值 */
    int8_t u_max_param;      /**< 参数序号，−1 = 用常数 u_max */
    float max_step;          /**< 0.14.0 物理上限：单次阶跃 |目标 − 当前设定值| 的最大值（link.step.max_step；0 = 不限），超了回 status 1 */
} dzstep_ch_t;

typedef struct {
    bool active;
    uint8_t ch, mode;
    uint16_t iter, n, n_ss, n_sat, n_u;
    uint32_t t0, dur, hash, rise10, rise90, settle_t;
    bool settle_pending, last_out;
    float sp, y0, band, u_max, umax_r, ss_sum, peak, maxr;
} dzstep_t;

/** CRC32/IEEE（反射多项式 0xEDB88320，初值/结果异或 0xFFFFFFFF），与 Python zlib.crc32 相同。 */
uint32_t dzctl_crc32(const void *data, uint32_t len);
/** #38 params_hash：参数表顺序，每个参数的当前值（dzctl_get，整型也换成 float）按 little-endian float32 拼接后 CRC32。 */
uint32_t dzctl_params_crc32(const dzctl_table_t *t);

/** 参数写入校验（不写）：0 = 可写，否则 DZSTEP_REJ_*。cur = 当前值，locked = 急停锁存或实验进行中。 */
uint8_t dzctl_param_check(const dzctl_table_t *t, uint8_t i, float v, bool locked);
/** 处理一帧 PARAM_SET（读 / 带校验的写）：不是 PARAM_SET 返回 false。写被拒 → ack status=DZCTL_REJECTED，
 *  *has_rej = true 且 rej 填好 param_reject 帧（调用方先发 ack 再发 rej）。 */
bool dzctl_handle_checked(const dzctl_table_t *t, const dzframe_t *in, bool locked, dzframe_t *ack, dzframe_t *rej, bool *has_rej);
void dzstep_reject_frame(const dzctl_table_t *t, uint8_t i, uint8_t reason, float req, dzframe_t *out);

/** 解析开始帧；返回 DZSTEP_ST_*（只校验格式），解析出 ch/iter/target/dur。len=0 = 停止请求，返回 0xFF。 */
uint8_t dzstep_parse(const dzframe_t *f, uint8_t n_ch, uint8_t *ch, uint16_t *iter, float *target, uint32_t *dur);
void dzstep_ack(uint8_t status, uint8_t ch, uint16_t iter, uint8_t seq, dzframe_t *out);
void dzstep_begin(dzstep_t *s, const dzstep_ch_t *c, uint8_t ch, uint16_t iter, float sp, uint32_t dur, uint32_t t0, uint32_t hash, float u_max);
/** 喂一个样本（遥测节拍）；u 为 NaN = 应用不提供输出。窗口到了返回 true（调用方随后 dzstep_finish）。 */
bool dzstep_sample(dzstep_t *s, uint32_t t, float y, float u);
/** 结束并填 step_result；aborted 时 cause 为原因。之后 s->active = false。 */
void dzstep_finish(dzstep_t *s, bool aborted, uint8_t cause, uint8_t seq, dzframe_t *out);

int dzstep_selftest(void);

#endif
