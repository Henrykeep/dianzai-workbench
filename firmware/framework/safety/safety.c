#include "safety.h"
#include <string.h>

dz_err_t safety_init(safety_t *s, const stall_cfg_t *cfg, uint8_t nch, bb_t *bb)
{
    if (!s || !cfg || nch == 0u || nch > SAFETY_MAX_CH) return DZ_EINVAL;
    memset(s, 0, sizeof *s);
    for (uint8_t i = 0; i < nch; i++) {
        dz_err_t e = stall_init(&s->ch[i], cfg);
        if (e != DZ_OK) return e;
    }
    s->n = nch; s->bb = bb;
    return DZ_OK;
}

bool safety_boot(safety_t *s, uint32_t reset_cause, bool fault, uint32_t now_ms)
{
    if (s->bb) bb_log(s->bb, now_ms, BB_EV_RESET, (uint16_t)reset_cause, 0.0f, 0.0f);
    if (fault) s->flags |= SAFETY_F_SAFE_BOOT;
    return fault;
}

bool safety_update(safety_t *s, uint8_t ch, float load, float speed, uint32_t now_ms)
{
    if (ch >= s->n) return false;
    uint8_t bit = (uint8_t)(1u << ch);
    if (stall_update(&s->ch[ch], load, speed, now_ms) != STALL_STALLED) return (s->stalled_mask & bit) != 0u;
    if (!(s->stalled_mask & bit)) {
        s->stalled_mask |= bit; s->flags |= SAFETY_F_STALL;
        if (s->bb) bb_log(s->bb, now_ms, BB_EV_STALL, ch, load, speed);
    }
    return true;
}

void safety_set_stall(safety_t *s, float load_on, uint32_t hold_ms)
{
    for (uint8_t i = 0; i < s->n; i++) { s->ch[i].c.load_on = load_on; s->ch[i].c.hold_ms = hold_ms; }
}

bool safety_latched(const safety_t *s) { return (s->flags & (SAFETY_F_SAFE_BOOT | SAFETY_F_STALL)) != 0u; }
uint32_t safety_flags(const safety_t *s) { return s->flags; }

void safety_clear(safety_t *s, uint32_t now_ms)
{
    if (s->flags && s->bb) bb_log(s->bb, now_ms, BB_EV_CLEAR, s->stalled_mask, 0.0f, 0.0f);
    for (uint8_t i = 0; i < s->n; i++) stall_clear(&s->ch[i]);
    s->stalled_mask = 0u; s->flags = 0u;
}

dz_err_t safety_selftest(void)
{
    safety_t s; bb_t bb; bb_rec_t ring[8];
    stall_cfg_t c = { .load_on = 0.8f, .speed_on = 0.2f, .hold_ms = 100u, .start_ignore_ms = 0u, .retry_ms = 0u };
    int fail = 0;
    fail += bb_init(&bb, ring, 8u, NULL) != DZ_OK;
    fail += safety_init(&s, &c, 0u, &bb) != DZ_EINVAL;
    fail += safety_init(&s, &c, 2u, &bb) != DZ_OK;
    fail += safety_boot(&s, 1u, false, 0u) || safety_latched(&s);
    for (uint32_t t = 0; t <= 300u; t += 10u) { (void)safety_update(&s, 0, 0.9f, 0.0f, t); (void)safety_update(&s, 1, 0.3f, 2.0f, t); }
    fail += !safety_latched(&s) || s.stalled_mask != 1u || !(safety_flags(&s) & SAFETY_F_STALL);
    fail += bb_count(&bb) != 2u || bb_get(&bb, 1)->code != BB_EV_STALL || bb_get(&bb, 1)->arg != 0u;
    (void)safety_update(&s, 0, 0.9f, 0.0f, 400u);
    fail += bb_count(&bb) != 2u;                       /* 锁存期间不重复记 */
    safety_clear(&s, 500u);
    fail += safety_latched(&s) || bb_get(&bb, 2)->code != BB_EV_CLEAR;
    fail += !safety_boot(&s, 4u, true, 600u) || !(safety_flags(&s) & SAFETY_F_SAFE_BOOT);
    return fail ? DZ_EFAIL : DZ_OK;
}
