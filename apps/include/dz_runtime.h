/**
 * @file dz_runtime.h
 * @brief 通用固件运行时（dzctl 0.12.0）：每个应用默认就有 —— 上电自检上报、联机/脱机运行模式、参数存 flash、上位机重跑自检。
 *        应用只注册自己的自检项（dzctl_selftest_register），其余（参数越界检查、flash 读写、模式持久化、按键、心跳标志）都在这里。
 *        只在应用的 app_main.c 里包含一次（全是 static inline）。link_app.h 已经集成；自己写收发循环的应用（car_2wd、2026H io）直接用。
 *
 * 用法：
 *   static dzrt_t R;
 *   dzrt_boot(&R, &g_link_params, &g_link_params_default, still_fn, send_fn);   // 读模式 + 读参数（失败 → 默认值）
 *   dzctl_selftest_register(DZCTL_ST_SENSOR, my_sensor_ok);                     // 应用自己的项
 *   uint32_t m = dzrt_selftest(&R, now);  dzrt_start(&R, m == 0, auto_start);
 *   收帧：if (dzrt_cmd(&R, &f)) continue;      // 'W' 'M'(len≥3) 'H'
 *   主循环：dzrt_poll(&R, now, estop);        // 处理请求、按键、心跳标志、参数指纹
 *
 * 命令（DATA DZCTL_ID_CMD）：
 *   'W'            → {'W', DZCTL_SAVE_*}           只在 still() 时写（擦扇区会卡 CPU）
 *   'M' 模式 0xA5  → {'M', 0 成功 / 1 没停稳 / 2 无 flash / 3 写失败 / 4 确认字节或模式非法}
 *   'H'            → {'H', u32 fail_mask}          重跑全部自检（含应用注册的项），心跳自检字段同步更新
 * flash 键（persist_kv）：1 = 参数块（带 schema 哈希），2 = 黑匣子（应用可用），3 = 运行模式。
 */
#ifndef DZ_RUNTIME_H
#define DZ_RUNTIME_H

#include <string.h>
#include "board_gen.h"
#include "dzframe.h"
#include "dzctl.h"
#include "link_gen.h"
#include "persist.h"
#include "nvm_pal.h"
#include "runmode.h"
#include "blackbox.h"

/* 参数结构：app.yaml 的 link.params → link_params_t（默认）；project.yaml 顶层 params → 包含前 #define DZRT_PARAMS_T params_t */
#ifndef DZRT_PARAMS_T
#define DZRT_PARAMS_T link_params_t
#endif

#define DZRT_KEY_PARAMS 1u
#define DZRT_KEY_BB     2u
#define DZRT_KEY_MODE   3u

typedef struct {
    DZRT_PARAMS_T *p;                  /**< 当前生效参数（2026H 换 profile 时应用改这个指针） */
    const DZRT_PARAMS_T *def;
    bool (*still)(void);               /**< 停稳了（才许存参/切模式）；NULL = 只在急停时算停稳 */
    void (*send)(const dzframe_t *f);
    bb_t *bb;                          /**< 可选：存参结果记黑匣子 */
    persist_flash_t nvf;
    persist_kv_t kv;
    bool have_kv;
    runmode_t rm;
    bool flash_ok;
    uint32_t flash_h, last_hash_ms;
    uint8_t param_src;                 /**< 0 flash / 1 未存过 / 2 flash 损坏或越界 / 3 无 flash */
    uint32_t st_mask;
    bool estop_now;
    volatile bool save_req, st_req;
    volatile uint8_t mode_req, mode_magic;
} dzrt_t;

static inline bool dzrt_params_sane_p(const DZRT_PARAMS_T *p)
{
    DZRT_PARAMS_T tmp = *p;
    dzctl_table_t t = link_param_table(&tmp);
    for (uint8_t i = 0; i < t.n; i++) {
        float g = dzctl_get(&t, i), v;
        if (g != g || dzctl_set(&t, i, g, &v) != DZCTL_OK || v != g) return false;
    }
    return true;
}

static inline uint8_t dzrt_load_params(dzrt_t *R)
{
    DZRT_PARAMS_T tmp;
    uint16_t n0 = 0;
    if (!R->have_kv) return 3u;
    dz_err_t rc = persist_blob_load(&R->kv, DZRT_KEY_PARAMS, LINK_SCHEMA_HASH, &tmp, (uint16_t)sizeof tmp);
    if (rc != DZ_OK) return rc == DZ_EFAIL && persist_kv_get(&R->kv, DZRT_KEY_PARAMS, &tmp, 0u, &n0) == DZ_EFAIL ? 1u : 2u;
    {
        dzctl_table_t src = link_param_table(&tmp), dst = link_param_table(R->p);
        for (uint8_t i = 0; i < src.n; i++) {
            float v;
            if (dzctl_set(&dst, i, dzctl_get(&src, i), &v) != DZCTL_OK) { *R->p = *R->def; return 2u; }
        }
    }
    R->flash_ok = true; R->flash_h = dzctl_hash32(R->p, (uint32_t)sizeof *R->p);
    return 0u;
}

/** 上电：flash 布局 → 运行模式 → 参数（结构哈希对得上且每个值在范围内才用，否则默认值）。返回参数来源 0..3。 */
static inline uint8_t dzrt_boot(dzrt_t *R, DZRT_PARAMS_T *p, const DZRT_PARAMS_T *def, bool (*still)(void), void (*send)(const dzframe_t *))
{
    uint8_t m = RUNMODE_TETHERED; uint16_t n = 0;
    memset(R, 0, sizeof *R);
    R->p = p; R->def = def; R->still = still; R->send = send;
    R->mode_req = 0xFFu;
    R->have_kv = nvm_pal_layout(&R->nvf, NULL, 0u) == DZ_OK && persist_kv_init(&R->kv, &R->nvf) == DZ_OK;
    if (R->have_kv && persist_kv_get(&R->kv, DZRT_KEY_MODE, &m, 1u, &n) != DZ_OK) m = RUNMODE_TETHERED;
    runmode_init(&R->rm, m);
    R->param_src = dzrt_load_params(R);
    dzctl_set_flags(DZCTL_HB_PARAMS_MASK, false);
    dzctl_set_flags((uint32_t)R->param_src << DZCTL_HB_PARAMS_SHIFT, true);
    dzctl_set_flags(DZCTL_HB_STANDALONE, R->rm.mode == RUNMODE_STANDALONE);
    return R->param_src;
}

/** 跑全部自检（通用：参数越界；加上应用注册的项），上报心跳并返回失败 mask。 */
static inline uint32_t dzrt_selftest(dzrt_t *R, uint32_t now)
{
    R->st_mask = dzctl_selftest_run(now, dzrt_params_sane_p(R->p) ? 0u : 1u << (DZCTL_ST_PARAMS - 1u));
    dzctl_set_flags(DZCTL_HB_SELFTEST_FAIL, R->st_mask != 0u);
    return R->st_mask;
}

/** 上电自检之后：脱机 + auto_start + 自检通过 → 自启。 */
static inline void dzrt_start(dzrt_t *R, bool selftest_ok, bool auto_start) { runmode_boot(&R->rm, selftest_ok, auto_start); }

static inline bool dzrt_needs_host(const dzrt_t *R) { return runmode_needs_host(&R->rm); }
/** 脱机已启动（板上按键 / 自启）。联机模式恒 false。 */
static inline bool dzrt_sa_running(const dzrt_t *R) { return R->rm.mode == RUNMODE_STANDALONE && R->rm.started; }

static inline bool dzrt_is_still(const dzrt_t *R) { return R->estop_now || (R->still && R->still()); }

/** 收帧时调用：运行时命令就记下请求（主循环里执行，不在收帧里写 flash）并返回 true。 */
static inline bool dzrt_cmd(dzrt_t *R, const dzframe_t *f)
{
    if (f->kind != DZF_DATA || f->id != DZCTL_ID_CMD || f->len < 1u) return false;
    uint8_t c = f->payload[0];
    if (c == 'W' && f->len == 1u) { R->save_req = true; return true; }
    if (c == DZCTL_CMD_SELFTEST && f->len == 1u) { R->st_req = true; return true; }
    if (c == 'M' && f->len >= 3u) {   /* 2 字节的 'M' 留给应用/仿真钩子（如 pan_tilt 仿真） */
        R->mode_magic = f->payload[2];
        R->mode_req = f->payload[1] == 0xFFu ? 0xFEu : f->payload[1];
        return true;
    }
    return false;
}

static inline void dzrt_reply2(dzrt_t *R, uint8_t c, uint8_t v)
{
    dzframe_t f;
    memset(&f, 0, sizeof f); f.kind = DZF_DATA; f.id = DZCTL_ID_CMD;
    (void)dzframe_put_u8(&f, c); (void)dzframe_put_u8(&f, v);
    if (R->send) R->send(&f);
}

/** 切模式：只在停稳时；写 flash 成功才生效。返回 'M' 回执码。 */
static inline uint8_t dzrt_set_mode(dzrt_t *R, uint8_t mode)
{
    uint8_t rc = !dzrt_is_still(R) ? 1u : !R->have_kv ? 2u : persist_kv_put(&R->kv, DZRT_KEY_MODE, &mode, 1u) == DZ_OK ? 0u : 3u;
    if (rc == 0u) { R->rm.mode = mode; R->rm.started = false; }
    return rc;
}

static inline uint8_t dzrt_save(dzrt_t *R, uint32_t now)
{
    dz_err_t rc = !R->have_kv ? DZ_ENOTSUP : !dzrt_is_still(R) ? DZ_EBUSY
                : persist_blob_save(&R->kv, DZRT_KEY_PARAMS, LINK_SCHEMA_HASH, R->p, (uint16_t)sizeof *R->p);
    if (rc == DZ_OK) { R->flash_ok = true; R->flash_h = dzctl_hash32(R->p, (uint32_t)sizeof *R->p); }
    if (R->bb) bb_log(R->bb, now, BB_EV_PARAM_SAVE, (uint16_t)(rc < 0 ? -rc : rc), 0.0f, 0.0f);
    return (uint8_t)(rc == DZ_OK ? DZCTL_SAVE_OK : rc == DZ_EBUSY ? DZCTL_SAVE_BUSY : rc == DZ_ENOTSUP ? DZCTL_SAVE_NO_NVM : DZCTL_SAVE_FAIL);
}

/** 主循环每拍：执行 'W'/'M'/'H' 请求、板上按键（RES_GPIO_KEY：脱机短按启停、长按 3 s 切模式）、心跳标志与参数指纹。
 *  key_override ≥ 0 时用它当按键状态（仿真/应用自己读键），−1 = 读 RES_GPIO_KEY（没有就当没按）。 */
static inline void dzrt_poll(dzrt_t *R, uint32_t now, bool estop, int key_override)
{
    bool key = false;
    R->estop_now = estop;
    if (R->save_req) { R->save_req = false; dzrt_reply2(R, 'W', dzrt_save(R, now)); }
    if (R->mode_req != 0xFFu) {
        uint8_t m = R->mode_req, rc = runmode_check_cmd(m, R->mode_magic, DZCTL_MODE_MAGIC);
        R->mode_req = 0xFFu;
        if (rc == 0u) rc = dzrt_set_mode(R, m);
        dzrt_reply2(R, 'M', rc);
    }
    if (R->st_req) {
        dzframe_t f;
        R->st_req = false;
        dzctl_selftest_reply(dzrt_selftest(R, now), &f);
        if (R->send) R->send(&f);
    }
    if (key_override >= 0) key = key_override != 0;
#ifdef RES_GPIO_KEY
    else if (pal_gpio_read(RES_GPIO_KEY, &key) != DZ_OK) key = false;
#endif
    {
        runmode_ev_t ev = runmode_button(&R->rm, key, now);
        if (ev == RUNMODE_EV_TOGGLE) (void)dzrt_set_mode(R, R->rm.mode == RUNMODE_STANDALONE ? RUNMODE_TETHERED : RUNMODE_STANDALONE);
        else if (ev == RUNMODE_EV_START && !estop) R->rm.started = true;
        else if (ev == RUNMODE_EV_STOP) R->rm.started = false;
    }
    if (estop) R->rm.started = false;
    dzctl_set_flags(DZCTL_HB_STANDALONE, R->rm.mode == RUNMODE_STANDALONE);
    dzctl_set_flags(DZCTL_HB_SA_RUNNING, dzrt_sa_running(R));
    if ((uint32_t)(now - R->last_hash_ms) >= 100u || R->last_hash_ms == 0u) {
        uint32_t h = dzctl_hash32(R->p, (uint32_t)sizeof *R->p);
        R->last_hash_ms = now ? now : 1u;
        dzctl_set_params_hash(h);
        dzctl_set_flags(DZCTL_HB_PARAMS_DIRTY, !R->flash_ok || h != R->flash_h);
    }
}

/** 心跳节拍（所有应用共用）：每拍按 estop 置 / 清 DZCTL_HB_ESTOP；急停上升沿和下降沿（'R' 解锁存）都立刻发一帧心跳
 *  （上位机 ≤ 5 ms 看到 bit10 置 / 清；只是通知，不恢复输出——不自动恢复由调用方的 estop/设定值清零保证），否则每 500 ms 一帧。返回 true = 现在发心跳。*last_hb 初值取 0u - 500u（复位后第一拍就发）。 */
static inline bool dzrt_hb_due(uint32_t now, bool estop, bool *was_estop, uint32_t *last_hb)
{
    bool edge = estop != *was_estop;   /* 两个沿都立即发 */
    *was_estop = estop;
    dzctl_set_flags(DZCTL_HB_ESTOP, estop);
    if (!edge && now - *last_hb < 500u) return false;
    *last_hb = now;
    return true;
}

#endif
