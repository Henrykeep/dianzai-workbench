/* 通用框架测试：用测试里临时定义的两个假子系统，不依赖任何具体题目。 */
#include "tt.h"
#include "subsys.h"
#include "coord.h"
#include "rtosmon.h"
#include "blackbox.h"
#include "safety.h"
#include <string.h>

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

TEST(coord_selftest_passes) { CHECK(coord_selftest() == DZ_OK); }

TEST(rtosmon_cpu_and_stack)
{
    CHECK(rtosmon_selftest() == DZ_OK);
    rtosmon_t m; rtosmon_init(&m);
    rtosmon_feed_cpu(&m, 100u, 100u);
    CHECK(rtosmon_cpu_permille(&m) == RTOSMON_NA);               /* 第一次只记基准 */
    rtosmon_feed_cpu(&m, 100u, 100u);
    CHECK(rtosmon_cpu_permille(&m) == RTOSMON_NA);               /* 时间没走：不更新 */
    rtosmon_feed_cpu(&m, 1100u, 1100u);  CHECK(m.cpu_pm == 0u);    /* 全在空闲 */
    rtosmon_feed_cpu(&m, 1100u, 2100u);  CHECK(m.cpu_pm == 1000u); /* 满载 */
    rtosmon_feed_cpu(&m, 2200u, 3100u);  CHECK(m.cpu_pm == 0u);    /* idle 增量略大于 total（读的先后）：钳到 0 */
    rtosmon_begin_stack(&m);
    rtosmon_feed_stack(&m, "a_very_long_task_name_xx", 70000u);
    CHECK(rtosmon_stack_min_words(&m) == RTOSMON_NA);            /* 没 end：不外泄半轮 */
    rtosmon_feed_stack(&m, "b", 40u);
    rtosmon_end_stack(&m);
    CHECK(m.stk_min_w == 40u && strcmp(m.worst, "b") == 0 && m.n_tasks == 2u && !rtosmon_stack_low(&m, 32u));
    rtosmon_begin_stack(&m); rtosmon_end_stack(&m);
    CHECK(m.stk_min_w == 40u);                                    /* 空扫描不覆盖 */
}

/* ---- blackbox：存储失败不能挡住启动 ---- */
typedef struct { uint8_t mem[16u + 8u * 16u]; int fail_erase, fail_write, fail_read, ops; } bbf_t;
static dz_err_t bbf_erase(void *c) { bbf_t *f = c; f->ops++; if (f->fail_erase) return DZ_EIO; memset(f->mem, 0xFF, sizeof f->mem); return DZ_OK; }
static dz_err_t bbf_write(void *c, uint32_t o, const void *p, uint32_t n)
{ bbf_t *f = c; f->ops++; if (f->fail_write || o + n > sizeof f->mem) return DZ_EIO; memcpy(f->mem + o, p, n); return DZ_OK; }
static dz_err_t bbf_read(void *c, uint32_t o, void *p, uint32_t n)
{ bbf_t *f = c; f->ops++; if (f->fail_read || o + n > sizeof f->mem) return DZ_EIO; memcpy(p, f->mem + o, n); return DZ_OK; }
static int bb_lines; static void bb_put(void *c, const char *l) { (void)c; bb_lines += (strncmp(l, "BB,", 3) == 0); }

/* 模拟“启动”：init + 读上次冻结 + 进入控制循环记 100 条。返回进到循环的条数（必须是 100，不管存储怎样）。 */
static uint32_t bb_boot(bbf_t *f, bb_t *bb, bb_rec_t *ring)
{
    bb_store_t st = { bbf_erase, bbf_write, bbf_read, f, sizeof f->mem };
    static bb_store_t keep; keep = st;
    bb_rec_t prev[8]; uint16_t n;
    if (bb_init(bb, ring, 8u, &keep) != DZ_OK) return 0u;
    (void)bb_load_frozen(bb, prev, 8u, &n);                       /* 结果无所谓：失败也继续 */
    uint32_t k = 0;
    for (; k < 100u; k++) bb_log(bb, k, 1u, 0u, (float)k, 0.0f);
    return k;
}

TEST(blackbox_ring_freeze_reload)
{
    CHECK(bb_selftest() == DZ_OK);
    CHECK(safety_selftest() == DZ_OK);
    static bbf_t f; memset(&f, 0, sizeof f); memset(f.mem, 0xFF, sizeof f.mem);
    bb_t bb; bb_rec_t ring[8], out[8]; uint16_t n;
    CHECK(bb_boot(&f, &bb, ring) == 100u && bb_count(&bb) == 8u && bb_get(&bb, 0)->t_ms == 92u);
    CHECK(bb_freeze(&bb) == DZ_OK);
    bb_t bb2; bb_rec_t ring2[8];                                  /* “复位”后读回 */
    CHECK(bb_boot(&f, &bb2, ring2) == 100u);
    CHECK(bb_load_frozen(&bb2, out, 8u, &n) == DZ_OK && n == 8u && out[0].t_ms == 92u && out[7].a == 99.0f);
    CHECK(bb_load_frozen(&bb2, out, 4u, &n) == DZ_EINVAL && n == 0u);   /* 缓冲小：不截断 */
    f.mem[20] ^= 0x5Au;                                           /* 记录被改：校验不过 */
    CHECK(bb_load_frozen(&bb2, out, 8u, &n) == DZ_EFAIL);
    bb_lines = 0; CHECK(bb_dump(ring, 3u, bb_put, NULL) == 3u && bb_lines == 3);
    bb_t r; bb_rec_t rr[4];
    CHECK(bb_init(&r, rr, 4u, NULL) == DZ_OK && bb_freeze(&r) == DZ_ENOTSUP && bb_init(&r, rr, 0u, NULL) == DZ_EINVAL);
}

TEST(blackbox_store_failure_never_blocks_boot)
{
    static bbf_t f; bb_t bb; bb_rec_t ring[8];
    memset(&f, 0, sizeof f); f.fail_erase = f.fail_write = f.fail_read = 1;   /* 坏 flash：读写擦全失败 */
    CHECK(bb_boot(&f, &bb, ring) == 100u && bb_count(&bb) == 8u);           /* 启动照常、RAM 日志照常 */
    CHECK(f.ops == 1);                                                      /* 启动路径只碰存储 1 次（读头），不重试 */
    CHECK(bb_freeze(&bb) == DZ_EIO && bb_freeze(&bb) == DZ_EIO);            /* 已 3 次失败（读 1 + 擦 2） */
    CHECK(!bb_store_usable(&bb) && bb.st_errors == 3u);
    int before = f.ops;
    CHECK(bb_freeze(&bb) == DZ_ENOTSUP && f.ops == before);                 /* 停用后一次都不再碰 */
    bb_log(&bb, 1000u, 9u, 0u, 0.0f, 0.0f); CHECK(bb_get(&bb, 7)->code == 9u);
    memset(&f, 0, sizeof f); f.fail_write = 1; memset(f.mem, 0xFF, sizeof f.mem); /* 擦成功、写失败（写满/掉电）：头没写 → 下次读到“无” */
    CHECK(bb_boot(&f, &bb, ring) == 100u && bb_freeze(&bb) == DZ_EIO);
    f.fail_write = 0; { bb_rec_t o[8]; uint16_t n; CHECK(bb_load_frozen(&bb, o, 8u, &n) == DZ_EFAIL && n == 0u); }
    CHECK(bb_freeze(&bb) == DZ_OK && bb.st_fail == 0u);                     /* 恢复后成功清零连续失败 */
}

void suite_framework(void) { RUN(blackbox_ring_freeze_reload); RUN(blackbox_store_failure_never_blocks_boot); RUN(rtosmon_cpu_and_stack); RUN(coord_selftest_passes); RUN(sched_rejects_bad); RUN(sched_periods_modes_overrun_wrap); RUN(coord_state_machine); }
