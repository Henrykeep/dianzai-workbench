#include "key.h"

dz_err_t key_init(dz_key_t *k, const key_cfg_t *cfg)
{
    if (!k || !cfg || cfg->long_ms <= cfg->debounce_ms) return DZ_EINVAL;
    k->cfg = *cfg;
    k->raw = k->stable = k->long_sent = k->primed = false;
    k->raw_since = k->press_at = k->last_rep = 0u;
    return DZ_OK;
}

key_event_t key_feed(dz_key_t *k, bool pressed, uint32_t now)
{
    if (!k) return KEY_EV_NONE;
    if (!k->primed) { k->primed = true; k->raw = pressed; k->raw_since = now; }
    if (pressed != k->raw) { k->raw = pressed; k->raw_since = now; }
    if (k->raw != k->stable && (uint32_t)(now - k->raw_since) >= k->cfg.debounce_ms) {
        k->stable = k->raw;
        if (k->stable) { k->press_at = now; k->long_sent = false; return KEY_EV_NONE; }
        return k->long_sent ? KEY_EV_NONE : KEY_EV_SHORT;
    }
    if (k->stable) {
        if (!k->long_sent && (uint32_t)(now - k->press_at) >= k->cfg.long_ms) {
            k->long_sent = true; k->last_rep = now; return KEY_EV_LONG;
        }
        if (k->long_sent && k->cfg.repeat_ms && (uint32_t)(now - k->last_rep) >= k->cfg.repeat_ms) {
            k->last_rep = now; return KEY_EV_REPEAT;
        }
    }
    return KEY_EV_NONE;
}

key_event_t key_poll(dz_key_t *k)
{
    bool on = false;
    if (!k || pal_gpio_read(k->cfg.gpio, &on) != DZ_OK) return KEY_EV_NONE;
    return key_feed(k, on, pal_millis());
}

bool key_is_down(const dz_key_t *k) { return k && k->stable; }

dz_err_t key_selftest(void)
{
    dz_key_t k; key_cfg_t c = { PAL_ID_NONE, 20u, 500u, 0u };
    uint32_t t; int shorts = 0, longs = 0;
    if (key_init(&k, &c) != DZ_OK) return DZ_EFAIL;
    for (t = 0u; t < 100u; t++) shorts += key_feed(&k, (t % 3u) == 0u, t) == KEY_EV_SHORT; /* 抖动 */
    for (; t < 200u; t++) shorts += key_feed(&k, true, t) == KEY_EV_SHORT;
    for (; t < 300u; t++) shorts += key_feed(&k, false, t) == KEY_EV_SHORT;
    for (; t < 1000u; t++) longs += key_feed(&k, true, t) == KEY_EV_LONG;
    for (; t < 1100u; t++) shorts += key_feed(&k, false, t) == KEY_EV_SHORT;
    return (shorts == 1 && longs == 1) ? DZ_OK : DZ_EFAIL;
}
