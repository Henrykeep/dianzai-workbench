#include "coord.h"

static void go(coord_t *c, coord_state_t to, coord_event_t why)
{
    coord_state_t from = c->st;
    c->st = to;
    subsys_mode_t m = to == COORD_RUNNING ? SUBSYS_MODE_RUN
                    : (to == COORD_ESTOP || to == COORD_FAULT) ? SUBSYS_MODE_ESTOP : SUBSYS_MODE_IDLE;
    subsys_sched_set_mode(c->sched, m);
    if (c->hooks.on_state && from != to) c->hooks.on_state(from, to, why);
}

dz_err_t coord_init(coord_t *c, subsys_sched_t *sched, const coord_test_t *tests, uint8_t n_tests,
                    const coord_profile_t *profiles, uint8_t n_profiles, const coord_hooks_t *hooks)
{
    if (!c || !sched || !tests || !n_tests || !profiles || !n_profiles) return DZ_EINVAL;
    for (uint8_t i = 0; i < n_tests; i++) if (tests[i].profile >= n_profiles) return DZ_EINVAL;
    c->tests = tests; c->n_tests = n_tests; c->profiles = profiles; c->n_profiles = n_profiles;
    c->hooks = hooks ? *hooks : (coord_hooks_t){0};
    c->sched = sched; c->st = COORD_IDLE; c->estop_latched = false;
    c->test_idx = 0; c->profile_idx = tests[0].profile; c->t_start_ms = 0; c->now_ms = 0;
    subsys_sched_set_params(sched, profiles[c->profile_idx].params);
    subsys_sched_set_mode(sched, SUBSYS_MODE_IDLE);
    return DZ_OK;
}

static bool can_config(const coord_t *c) { return c->st == COORD_IDLE || c->st == COORD_DONE; }

dz_err_t coord_select_test(coord_t *c, uint8_t idx)
{
    if (!c) return DZ_EINVAL;
    if (idx >= c->n_tests) return DZ_EINVAL;
    if (!can_config(c)) return DZ_ESTATE;
    c->test_idx = idx;
    return coord_select_profile(c, c->tests[idx].profile);
}

dz_err_t coord_select_profile(coord_t *c, uint8_t idx)
{
    if (!c) return DZ_EINVAL;
    if (idx >= c->n_profiles) return DZ_EINVAL;
    if (!can_config(c)) return DZ_ESTATE;
    c->profile_idx = idx;
    subsys_sched_set_params(c->sched, c->profiles[idx].params);
    return DZ_OK;
}

dz_err_t coord_event(coord_t *c, coord_event_t ev)
{
    if (!c) return DZ_EINVAL;
    switch (ev) {
    case COORD_EV_ESTOP:  c->estop_latched = true; go(c, COORD_ESTOP, ev); return DZ_OK;  /* 任意状态都接受 */
    case COORD_EV_FAULT:  if (c->st == COORD_ESTOP) return DZ_OK; go(c, COORD_FAULT, ev); return DZ_OK;
    case COORD_EV_START:
        if (!can_config(c)) return DZ_ESTATE;
        c->t_start_ms = c->now_ms; go(c, COORD_RUNNING, ev); return DZ_OK;
    case COORD_EV_STOP:
    case COORD_EV_FINISHED:
        if (c->st != COORD_RUNNING) return DZ_ESTATE;
        go(c, COORD_DONE, ev); return DZ_OK;
    case COORD_EV_RESET:
        if (c->st == COORD_RUNNING) return DZ_ESTATE;    /* 运行中要先 stop，防止误触复位 */
        c->estop_latched = false; go(c, COORD_IDLE, ev); return DZ_OK;
    }
    return DZ_EINVAL;
}

void coord_poll(coord_t *c, uint32_t now_ms)
{
    if (!c) return;
    c->now_ms = now_ms;
    const coord_test_t *t = &c->tests[c->test_idx];
    uint32_t tin = c->st == COORD_RUNNING ? now_ms - c->t_start_ms : 0;
    if (c->st == COORD_RUNNING) {
        if (t->time_limit_ms && tin >= t->time_limit_ms) { coord_event(c, COORD_EV_FINISHED); }
        else if (c->hooks.is_finished && c->hooks.is_finished(c->sched->state, t, tin)) coord_event(c, COORD_EV_FINISHED);
    }
    if (c->hooks.pre_step) c->hooks.pre_step(c->sched->state, t, c->sched->params, tin);
    subsys_sched_poll(c->sched, now_ms);
}

coord_state_t coord_state(const coord_t *c) { return c ? c->st : COORD_FAULT; }

const char *coord_state_name(coord_state_t s)
{
    static const char *const n[] = { "IDLE", "RUNNING", "DONE", "ESTOP", "FAULT" };
    return (unsigned)s < 5u ? n[s] : "?";
}

dz_err_t coord_selftest(void)
{
    static subsys_sched_t sched;
    static int dummy_state;
    static const coord_test_t tests[1] = { { 1, "t", 0, 100 } };
    static const coord_profile_t prof[1] = { { "p", 0 } };
    coord_t c;
    if (subsys_sched_init(&sched, 0, 0, &dummy_state, 0) != DZ_OK) return DZ_EIO;
    if (coord_init(&c, &sched, tests, 1, prof, 1, 0) != DZ_OK) return DZ_EIO;
    if (coord_event(&c, COORD_EV_STOP) != DZ_ESTATE) return DZ_EIO;          /* IDLE 下 STOP 非法 */
    if (coord_event(&c, COORD_EV_START) != DZ_OK || c.st != COORD_RUNNING) return DZ_EIO;
    if (sched.mode != SUBSYS_MODE_RUN) return DZ_EIO;
    if (coord_event(&c, COORD_EV_ESTOP) != DZ_OK || c.st != COORD_ESTOP) return DZ_EIO;
    if (sched.mode != SUBSYS_MODE_ESTOP) return DZ_EIO;
    if (coord_event(&c, COORD_EV_START) != DZ_ESTATE) return DZ_EIO;         /* 急停后必须先 RESET */
    if (coord_event(&c, COORD_EV_RESET) != DZ_OK || c.st != COORD_IDLE) return DZ_EIO;
    if (coord_event(&c, COORD_EV_START) != DZ_OK) return DZ_EIO;
    coord_poll(&c, 50);
    if (c.st != COORD_RUNNING) return DZ_EIO;
    coord_poll(&c, 200);                                                     /* 超过 100 ms 限时 */
    if (c.st == COORD_RUNNING) return DZ_EIO;
    return DZ_OK;
}
