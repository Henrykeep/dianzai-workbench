#include "subsys.h"

dz_err_t subsys_sched_init(subsys_sched_t *s, const subsys_t *const *list, uint8_t n,
                           void *state, const void *params)
{
    if (!s || (!list && n) || n > SUBSYS_MAX || !state) return DZ_EINVAL;
    for (uint8_t i = 0; i < n; i++)
        if (!list[i] || list[i]->period_ms == 0) return DZ_EINVAL;
    s->count = n; s->state = state; s->params = params; s->mode = SUBSYS_MODE_IDLE;
    for (uint8_t i = 0; i < n; i++) {
        s->list[i] = list[i]; s->next_ms[i] = 0; s->overrun[i] = 0; s->started[i] = false;
        if (list[i]->init) {
            dz_err_t e = list[i]->init(state, params);
            if (e != DZ_OK) return e;
        }
    }
    return DZ_OK;
}

void subsys_sched_poll(subsys_sched_t *s, uint32_t now)
{
    if (!s) return;
    for (uint8_t i = 0; i < s->count; i++) {
        const subsys_t *x = s->list[i];
        if (!s->started[i]) { s->started[i] = true; s->next_ms[i] = now; }
        if ((int32_t)(now - s->next_ms[i]) < 0) continue;
        if ((int32_t)(now - s->next_ms[i]) >= (int32_t)x->period_ms) {
            s->overrun[i]++;
            s->next_ms[i] = now;                     /* 落后一个周期以上：不补跑，重新对齐 */
        }
        s->next_ms[i] += x->period_ms;
        if (x->step && (x->run_always || s->mode == SUBSYS_MODE_RUN)) x->step(s->state, s->params, now);
    }
}

void subsys_sched_set_mode(subsys_sched_t *s, subsys_mode_t mode)
{
    if (!s || s->mode == mode) return;
    s->mode = mode;
    for (uint8_t i = 0; i < s->count; i++)
        if (s->list[i]->on_mode) s->list[i]->on_mode(s->state, mode);
}

void subsys_sched_set_params(subsys_sched_t *s, const void *params)
{
    if (s && params) s->params = params;
}

int subsys_sched_selftest(const subsys_sched_t *s)
{
    if (!s) return 0;
    for (uint8_t i = 0; i < s->count; i++)
        if (s->list[i]->selftest && s->list[i]->selftest() != DZ_OK) return i;
    return -1;
}
