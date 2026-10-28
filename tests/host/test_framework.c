/* 通用框架测试：用测试里临时定义的两个假子系统，不依赖任何具体题目。 */
#include "tt.h"
#include "subsys.h"
#include "coord.h"

typedef struct { int a_steps, b_steps, a_out; subsys_mode_t last_mode; int mode_calls; } st_t;
typedef struct { int gain; } prm_t;

static void a_step(void *s, const void *p, uint32_t now) { st_t *st = s; st->a_steps++; st->a_out = ((const prm_t *)p)->gain; (void)now; }
static void b_step(void *s, const void *p, uint32_t now) { ((st_t *)s)->b_steps++; (void)p; (void)now; }
static void a_mode(void *s, subsys_mode_t m) { ((st_t *)s)->last_mode = m; ((st_t *)s)->mode_calls++; }
static dz_err_t bad_init(void *s, const void *p) { (void)s; (void)p; return DZ_EIO; }
static dz_err_t fail_selftest(void) { return DZ_EFAIL; }

static const subsys_t A = { "a", 2, true,  0, a_step, a_mode, 0 };
static const subsys_t B = { "b", 5, false, 0, b_step, 0, fail_selftest };
static const subsys_t BAD = { "bad", 1, true, bad_init, 0, 0, 0 };
static const subsys_t ZERO = { "zero", 0, true, 0, 0, 0, 0 };

TEST(sched_rejects_bad)
{
    subsys_sched_t s; st_t st = {0}; prm_t p = {1};
    const subsys_t *l1[] = { &ZERO };
    CHECK(subsys_sched_init(&s, l1, 1, &st, &p) == DZ_EINVAL);
    const subsys_t *l2[] = { &A, &BAD };
    CHECK(subsys_sched_init(&s, l2, 2, &st, &p) == DZ_EIO);
    CHECK(subsys_sched_init(&s, l2, 17, &st, &p) == DZ_EINVAL);
    CHECK(subsys_sched_init(&s, l2, 1, 0, &p) == DZ_EINVAL);
}

TEST(sched_periods_modes_overrun_wrap)
{
    subsys_sched_t s; st_t st = {0}; prm_t p = {7};
    const subsys_t *l[] = { &A, &B };
    CHECK(subsys_sched_init(&s, l, 2, &st, &p) == DZ_OK);
    for (uint32_t t = 0; t < 100; t++) subsys_sched_poll(&s, t);
    CHECK(st.a_steps == 50);          /* 2 ms 周期，run_always */
    CHECK(st.b_steps == 0);           /* IDLE 下不跑 */
    subsys_sched_set_mode(&s, SUBSYS_MODE_RUN);
    CHECK(st.last_mode == SUBSYS_MODE_RUN && st.mode_calls == 1);
    subsys_sched_set_mode(&s, SUBSYS_MODE_RUN);
    CHECK(st.mode_calls == 1);        /* 同模式不重复通知 */
    for (uint32_t t = 100; t < 200; t++) subsys_sched_poll(&s, t);
    CHECK(st.b_steps == 20);
    subsys_sched_poll(&s, 1000);      /* 主循环卡顿 800 ms */
    CHECK(s.overrun[0] == 1 && s.overrun[1] == 1);
    /* 32 位毫秒回绕 */
    subsys_sched_t s2; st_t st2 = {0};
    subsys_sched_init(&s2, l, 1, &st2, &p);
    for (uint32_t t = UINT32_MAX - 9; t != 10; t++) subsys_sched_poll(&s2, t);
    CHECK(st2.a_steps == 10);
    CHECK(s2.overrun[0] == 0);
    prm_t p2 = {9};
    subsys_sched_set_params(&s2, &p2);
    subsys_sched_poll(&s2, 100);
    CHECK(st2.a_out == 9);
    CHECK(subsys_sched_selftest(&s) == 1);
}

static int finished_after_ms;
static coord_state_t last_to; static int transitions;
static bool fin(const void *s, const coord_test_t *t, uint32_t tin) { (void)s; (void)t; return finished_after_ms && tin >= (uint32_t)finished_after_ms; }
static void on_state(coord_state_t f, coord_state_t t, coord_event_t w) { (void)f; (void)w; last_to = t; transitions++; }

TEST(coord_state_machine)
{
    subsys_sched_t s; st_t st = {0}; prm_t pa = {1}, pb = {2};
    const subsys_t *l[] = { &A, &B };
    subsys_sched_init(&s, l, 2, &st, &pa);
    const coord_profile_t prof[] = { { "a", &pa }, { "b", &pb } };
    const coord_test_t tests[] = { { 1, "t1", 0, 0 }, { 2, "t2", 1, 500 } };
    const coord_test_t bad[] = { { 1, "x", 5, 0 } };
    coord_t c; coord_hooks_t h = { 0, fin, on_state };
    CHECK(coord_init(&c, &s, bad, 1, prof, 2, &h) == DZ_EINVAL);   /* 测试项引用不存在的参数档 */
    CHECK(coord_init(&c, &s, tests, 2, prof, 2, &h) == DZ_OK);
    CHECK(coord_state(&c) == COORD_IDLE);
    CHECK(coord_event(&c, COORD_EV_STOP) == DZ_ESTATE);
    CHECK(coord_select_test(&c, 5) == DZ_EINVAL);
    CHECK(coord_select_test(&c, 1) == DZ_OK && s.params == &pb);   /* 参数档跟随测试项 */
    CHECK(coord_event(&c, COORD_EV_START) == DZ_OK && s.mode == SUBSYS_MODE_RUN);
    CHECK(coord_select_test(&c, 0) == DZ_ESTATE);                  /* 运行中不允许换 */
    CHECK(coord_event(&c, COORD_EV_RESET) == DZ_ESTATE);           /* 运行中不允许直接复位 */
    for (uint32_t t = 0; t <= 500; t++) coord_poll(&c, t);
    CHECK(coord_state(&c) == COORD_DONE);                          /* 限时到 */
    CHECK(s.mode == SUBSYS_MODE_IDLE);
    coord_select_test(&c, 0); finished_after_ms = 100;
    coord_event(&c, COORD_EV_START);
    for (uint32_t t = 501; t < 700; t++) coord_poll(&c, t);
    CHECK(coord_state(&c) == COORD_DONE);                          /* is_finished 钩子 */
    coord_event(&c, COORD_EV_RESET); coord_event(&c, COORD_EV_START);
    CHECK(coord_event(&c, COORD_EV_ESTOP) == DZ_OK && s.mode == SUBSYS_MODE_ESTOP);
    CHECK(coord_event(&c, COORD_EV_START) == DZ_ESTATE);           /* 急停后必须先复位 */
    CHECK(coord_event(&c, COORD_EV_FAULT) == DZ_OK && coord_state(&c) == COORD_ESTOP); /* 急停优先于故障 */
    CHECK(coord_event(&c, COORD_EV_RESET) == DZ_OK && coord_state(&c) == COORD_IDLE);
    CHECK(last_to == COORD_IDLE && transitions >= 6);
    CHECK(coord_event(&c, COORD_EV_FAULT) == DZ_OK && st.last_mode == SUBSYS_MODE_ESTOP);
    CHECK(coord_state_name(COORD_FAULT)[0] == 'F' && coord_state_name((coord_state_t)99)[0] == '?');
}

void suite_framework(void) { RUN(sched_rejects_bad); RUN(sched_periods_modes_overrun_wrap); RUN(coord_state_machine); }
