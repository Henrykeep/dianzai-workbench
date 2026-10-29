/**
 * @file stall.c
 * @brief 见 stall.h。判据来源：MICU-auto-embedded（实验室/开源小组工程）templates/auto-embedded/refs/control-safety-limits.md 检查项 2；代码自写。
 */
#include "stall.h"
#include <math.h>
#include <string.h>

dz_err_t stall_init(stall_t *s, const stall_cfg_t *c)
{
    if (!s || !c || !(c->load_on > 0.0f) || !(c->speed_on >= 0.0f) || !isfinite(c->load_on) || !isfinite(c->speed_on)
        || c->hold_ms == 0u) return DZ_EINVAL;
    memset(s, 0, sizeof *s);
    s->c = *c;
    return DZ_OK;
}

void stall_clear(stall_t *s) { if (s) { s->st = STALL_NORMAL; s->loaded = false; } }

stall_state_t stall_update(stall_t *s, float load, float speed, uint32_t now_ms)
{
    if (!s) return STALL_NORMAL;
    if (!isfinite(load) || !isfinite(speed)) return s->st;              /* 数据坏：保持现状 */
    bool hi = fabsf(load) >= s->c.load_on;
    if (s->st == STALL_STALLED) {
        if (s->c.retry_ms && (uint32_t)(now_ms - s->t_stalled) >= s->c.retry_ms) { s->st = STALL_NORMAL; s->loaded = false; }
        else return s->st;
    }
    if (!hi) { s->loaded = false; s->st = STALL_NORMAL; return s->st; }
    if (!s->loaded) { s->loaded = true; s->t_load = now_ms; }
    if ((uint32_t)(now_ms - s->t_load) < s->c.start_ignore_ms) { s->st = STALL_NORMAL; return s->st; }
    if (fabsf(speed) > s->c.speed_on) { s->st = STALL_NORMAL; return s->st; }
    if (s->st == STALL_NORMAL) { s->st = STALL_SUSPECT; s->t_suspect = now_ms; }
    if ((uint32_t)(now_ms - s->t_suspect) >= s->c.hold_ms) { s->st = STALL_STALLED; s->t_stalled = now_ms; s->count++; }
    return s->st;
}

dz_err_t stall_selftest(void)
{
    stall_cfg_t c = { 1.0f, 0.1f, 50u, 100u, 0u };
    stall_t s;
    if (stall_init(&s, &c) != DZ_OK) return DZ_EFAIL;
    for (uint32_t t = 0; t <= 300u; t += 1u) (void)stall_update(&s, 2.0f, 0.0f, t);
    return (s.st == STALL_STALLED && s.count == 1u) ? DZ_OK : DZ_EFAIL;
}
