/**
 * @file link_step.h
 * @brief #38 阶跃实验的应用侧胶水（dzctl 0.13.0）：开始/停止帧、按遥测节拍喂样本、急停中止、心跳 bit17 ITER_BUSY。
 *        link_app.h 已集成（L.sp[] 应用不用改）；自己写收发循环的应用（car_2wd）直接调这几个函数。只在 app_main.c 里包含一次。
 *        指标在 firmware/proto/dzctl/dzstep.c 里算，仿真板与真板同一份代码。
 *
 *   收帧：int r = link_step_rx(&f, latched, offline, now, &tbl, &seq, send, &ch, &target);
 *         r == 0 不是阶跃帧；1 已处理（已回 ack / 结果）；2 已开始 → 调用方把设定值槽位 g_link_step[ch].sp_idx 设成 target
 *   遥测：link_step_on_telem(t_ms, y, u, &seq, send)   —— 每帧遥测调一次（u 没有给 NaN）
 *   急停：link_step_latch()（锁存那一刻：清 bit17、记待中止）；收发循环里 link_step_flush(&seq, send) 发 aborted 结果
 *   上位机中途又给设定值：link_step_preempt()（结果 aborted=1，cause=0x80）
 */
#ifndef LINK_STEP_H
#define LINK_STEP_H

#include "dzstep.h"
#include "link_gen.h"

static dzstep_t s_link_step;
static volatile bool s_link_step_abort;
static volatile uint8_t s_link_step_cause;

static inline bool link_step_busy(void) { return s_link_step.active; }

static inline void link_step_finish(bool aborted, uint8_t cause, uint8_t *seq, void (*send)(const dzframe_t *))
{
    dzframe_t out;
    dzctl_set_flags(DZCTL_HB_ITER_BUSY, false);
    if (!s_link_step.active) return;
    dzstep_finish(&s_link_step, aborted, cause, (*seq)++, &out);
    send(&out);
}

/** 急停锁存那一刻调用（可在任何上下文）：bit17 立即清 0，结果在下一次 link_step_flush 发。 */
static inline void link_step_latch(void)
{
    dzctl_set_flags(DZCTL_HB_ITER_BUSY, false);
    if (s_link_step.active) { s_link_step_abort = true; s_link_step_cause = 0u; }
}

static inline void link_step_preempt(void)
{
    if (s_link_step.active) { s_link_step_abort = true; s_link_step_cause = DZSTEP_AB_HOST_STOP; }
}

/** 发待中止的结果；cause 0 = 取急停原因（dzctl_estop_cause，0 也照发）。 */
static inline void link_step_flush(uint8_t *seq, void (*send)(const dzframe_t *))
{
    if (!s_link_step_abort) return;
    s_link_step_abort = false;
    link_step_finish(true, s_link_step_cause ? s_link_step_cause : (uint8_t)dzctl_estop_cause(), seq, send);
}

static inline int link_step_rx(const dzframe_t *f, bool latched, bool offline, uint32_t now, const dzctl_table_t *tbl,
                               uint8_t *seq, void (*send)(const dzframe_t *), uint8_t *ch, float *target)
{
    dzframe_t out;
    uint16_t iter; uint32_t dur;
    if (f->kind != DZF_DATA || f->id != DZSTEP_ID) return 0;
    uint8_t st = dzstep_parse(f, (uint8_t)LINK_STEP_N, ch, &iter, target, &dur);
    if (st == 0xFFu) {                                      /* 停止 */
        if (s_link_step.active) { s_link_step_abort = false; link_step_finish(true, DZSTEP_AB_HOST_STOP, seq, send); }
        else { dzstep_ack(DZSTEP_ST_STARTED, 0u, 0u, (*seq)++, &out); send(&out); }
        return 1;
    }
    if (st == DZSTEP_ST_STARTED) {
        if (latched) st = DZSTEP_ST_ESTOP;
        else if (offline) st = DZSTEP_ST_OFFLINE;
        else if (s_link_step.active) st = DZSTEP_ST_BUSY;
    }
    dzstep_ack(st, *ch, iter, (*seq)++, &out);
    send(&out);
    if (st != DZSTEP_ST_STARTED) return 1;
    const dzstep_ch_t *c = &g_link_step[*ch];
    float umax = c->u_max_param >= 0 ? dzctl_get(tbl, (uint8_t)c->u_max_param) : c->u_max;
    dzstep_begin(&s_link_step, c, *ch, iter, *target, dur, now, dzctl_params_crc32(tbl), umax);
    s_link_step_abort = false;
    dzctl_set_flags(DZCTL_HB_ITER_BUSY, true);
    return 2;
}

static inline void link_step_on_telem(uint32_t t_ms, float y, float u, uint8_t *seq, void (*send)(const dzframe_t *))
{
    if (!s_link_step.active || s_link_step_abort) return;
    if (dzstep_sample(&s_link_step, t_ms, y, u)) link_step_finish(false, 0u, seq, send);
}

#endif
