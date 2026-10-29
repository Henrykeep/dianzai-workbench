/**
 * @file keypad4x4.c
 * @brief 见 keypad4x4.h。
 * Source: LP-MSPM0G3507_freertos_firework@ede35a2 modules/matrix_keypad/matrix_keypad.c （MIT，Copyright (c) 2026 阡陌）
 */
#include "keypad4x4.h"
#include <string.h>

static const char CH[KP_KEYS] = { '1', '2', '3', 'A', '4', '5', '6', 'B', '7', '8', '9', 'C', '*', '0', '#', 'D' };

dz_err_t kp_init(keypad_t *k, const kp_cfg_t *c)
{
    if (!k || !c || c->debounce_ms == 0u) return DZ_EINVAL;
    memset(k, 0, sizeof *k);
    k->c = *c;
    return DZ_OK;
}

dz_err_t kp_debounce(keypad_t *k, uint16_t raw, uint32_t elapsed_ms, kp_event_t *ev)
{
    if (!k || !ev || elapsed_ms == 0u) return DZ_EINVAL;
    ev->pressed = ev->released = 0;
    for (uint32_t i = 0; i < KP_KEYS; i++) {
        uint16_t b = (uint16_t)(1u << i);
        bool r = raw & b, last = k->last_raw & b, st = k->stable & b;
        if (r != last) { k->last_raw ^= b; k->acc_ms[i] = 0; continue; }   /* 原始在变：重新计时 */
        if (r == st) { k->acc_ms[i] = 0; continue; }
        uint32_t a = (uint32_t)k->acc_ms[i] + elapsed_ms;
        k->acc_ms[i] = (uint16_t)(a > 0xFFFFu ? 0xFFFFu : a);              /* 饱和加 */
        if (k->acc_ms[i] < k->c.debounce_ms) continue;
        k->acc_ms[i] = 0;
        if (r) { k->stable |= b; ev->pressed |= b; } else { k->stable &= (uint16_t)~b; ev->released |= b; }
    }
    ev->held = k->stable;
    return DZ_OK;
}

static void idle(const keypad_t *k) { for (int r = 0; r < 4; r++) (void)pal_gpio_write(k->c.row[r], false); }

dz_err_t kp_scan_raw(keypad_t *k, uint16_t *raw)
{
    if (!k || !raw) return DZ_EINVAL;
    uint16_t bits = 0;
    idle(k);
    for (int r = 0; r < 4; r++) {
        dz_err_t e = pal_gpio_write(k->c.row[r], true);
        if (e) { idle(k); return e; }
        if (k->c.settle_us) pal_delay_us(k->c.settle_us);
        for (int c = 0; c < 4; c++) {
            bool on = false;
            e = pal_gpio_read(k->c.col[c], &on);
            if (e) { idle(k); return e; }
            if (on) bits |= (uint16_t)(1u << (r * 4 + c));
        }
        (void)pal_gpio_write(k->c.row[r], false);
    }
    *raw = bits;
    return DZ_OK;
}

dz_err_t kp_process(keypad_t *k, uint32_t elapsed_ms, kp_event_t *ev)
{
    uint16_t raw;
    dz_err_t e = kp_scan_raw(k, &raw);
    return e ? e : kp_debounce(k, raw, elapsed_ms, ev);
}

char kp_char(int key) { return (key >= 0 && key < (int)KP_KEYS) ? CH[key] : '\0'; }

int kp_first(uint16_t bits)
{
    for (int i = 0; i < (int)KP_KEYS; i++) if (bits & (1u << i)) return i;
    return KP_NONE;
}

dz_err_t keypad4x4_selftest(void)
{
    keypad_t k; kp_cfg_t c; kp_event_t ev;
    memset(&c, 0, sizeof c); c.debounce_ms = 20;
    if (kp_init(&k, &c)) return DZ_EFAIL;
    kp_debounce(&k, 0x1, 10, &ev);                 /* 变化：清零 */
    kp_debounce(&k, 0x1, 10, &ev);
    kp_debounce(&k, 0x1, 10, &ev);
    if (ev.pressed != 0x1 || kp_char(kp_first(ev.held)) != '1') return DZ_EFAIL;
    return DZ_OK;
}
