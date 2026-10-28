/**
 * @file key.h
 * @brief 按键消抖 + 短按/长按/长按连发事件。纯逻辑（key_feed）+ 可选的 pal_gpio 采样（key_poll）。
 *
 * 状态机：电平需连续稳定 debounce_ms 才认；按下→松开且未达 long_ms = 短按（松开时报）；
 * 按住达 long_ms 报一次长按，之后每 repeat_ms 报一次连发（repeat_ms=0 关闭）。
 * 参考：Jack Ganssle《A Guide to Debouncing》的时间积分思路；P2 工程的短按/长按设计。
 * 版本：KEY_VERSION
 */
#ifndef KEY_H
#define KEY_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "pal.h"
#define KEY_VERSION "1.0.0"

typedef enum { KEY_EV_NONE = 0, KEY_EV_SHORT, KEY_EV_LONG, KEY_EV_REPEAT } key_event_t;

typedef struct {
    pal_id_t gpio;          /**< board.yaml 里的 GPIO 逻辑 ID（active 即“按下”，极性在 board.yaml 配） */
    uint16_t debounce_ms;   /**< 典型 20 */
    uint16_t long_ms;       /**< 典型 800 */
    uint16_t repeat_ms;     /**< 0 = 不连发 */
} key_cfg_t;

typedef struct {
    key_cfg_t cfg;
    bool raw, stable, long_sent, primed;
    uint32_t raw_since, press_at, last_rep;
} dz_key_t;

dz_err_t key_init(dz_key_t *k, const key_cfg_t *cfg);
/** 喂一个电平样本（pressed=按下），返回本次产生的事件。 */
key_event_t key_feed(dz_key_t *k, bool pressed, uint32_t now_ms);
/** 读 pal_gpio 后调用 key_feed。 */
key_event_t key_poll(dz_key_t *k);
bool key_is_down(const dz_key_t *k);
dz_err_t key_selftest(void);
#endif
