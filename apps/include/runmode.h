/**
 * @file runmode.h
 * @brief 运行模式（联机 / 脱机）的纯逻辑：不碰硬件、不碰 flash，应用负责存取与执行。只在应用的 app_main.c 里包含一次。
 *
 *   TETHERED（联机，默认）：上位机给目标，心跳丢失 → 停车锁存急停（现有行为）。
 *   STANDALONE（脱机）：参数取自 flash；板上按键短按启动，或上电自检通过后自启（auto_start）；不要求心跳，
 *                      保护只靠板上（堵转 / 欠压 / 过流 / 限位）。
 *   切换只由人发起：上位机 'M'（带 DZCTL_MODE_MAGIC 确认字节，界面先弹确认卡）或板上按键长按 RUNMODE_LONG_MS；
 *   只在停着时切，固件从不自动切换。模式单独存 flash（与参数分开，存参数不会改模式）。
 */
#ifndef RUNMODE_H
#define RUNMODE_H

#include <stdbool.h>
#include <stdint.h>

#define RUNMODE_TETHERED   0u
#define RUNMODE_STANDALONE 1u
#define RUNMODE_LONG_MS    3000u   /* 长按 3 s 切模式 */
#define RUNMODE_DEBOUNCE_MS 30u

typedef struct {
    uint8_t mode;          /**< RUNMODE_* */
    bool    started;       /**< 脱机模式下已启动 */
    bool    btn, btn_long_done;
    uint32_t btn_ms;
} runmode_t;

typedef enum { RUNMODE_EV_NONE = 0, RUNMODE_EV_START, RUNMODE_EV_STOP, RUNMODE_EV_TOGGLE } runmode_ev_t;

static inline void runmode_init(runmode_t *r, uint8_t stored_mode)
{
    r->mode = stored_mode == RUNMODE_STANDALONE ? RUNMODE_STANDALONE : RUNMODE_TETHERED;   /* 读不到/非法 → 联机（安全侧） */
    r->started = false; r->btn = false; r->btn_long_done = false; r->btn_ms = 0u;
}

/** 心跳看门狗是否生效：只有联机模式要求上位机在线。 */
static inline bool runmode_needs_host(const runmode_t *r) { return r->mode != RUNMODE_STANDALONE; }

/** 上电自检之后调用：脱机 + auto_start + 自检通过 → 自启。 */
static inline void runmode_boot(runmode_t *r, bool selftest_ok, bool auto_start)
{
    r->started = r->mode == RUNMODE_STANDALONE && selftest_ok && auto_start;
}

/** 上位机 'M'：校验确认字节与模式值；返回 0 可以切（应用再判是否停稳、写 flash），4 = 不切。 */
static inline uint8_t runmode_check_cmd(uint8_t mode, uint8_t magic, uint8_t want_magic)
{
    return (magic == want_magic && (mode == RUNMODE_TETHERED || mode == RUNMODE_STANDALONE)) ? 0u : 4u;
}

/** 按键（已读成“按下 = true”），每拍调用。短按（松开时 < LONG）：脱机模式下启动/停止；长按满 LONG：请求切模式（只发一次）。 */
static inline runmode_ev_t runmode_button(runmode_t *r, bool pressed, uint32_t now)
{
    if (pressed && !r->btn) { r->btn = true; r->btn_ms = now; r->btn_long_done = false; return RUNMODE_EV_NONE; }
    if (pressed && !r->btn_long_done && (uint32_t)(now - r->btn_ms) >= RUNMODE_LONG_MS) { r->btn_long_done = true; return RUNMODE_EV_TOGGLE; }
    if (!pressed && r->btn) {
        uint32_t held = now - r->btn_ms;
        r->btn = false;
        if (r->btn_long_done || held < RUNMODE_DEBOUNCE_MS || r->mode != RUNMODE_STANDALONE) return RUNMODE_EV_NONE;
        return r->started ? RUNMODE_EV_STOP : RUNMODE_EV_START;
    }
    return RUNMODE_EV_NONE;
}

#endif
