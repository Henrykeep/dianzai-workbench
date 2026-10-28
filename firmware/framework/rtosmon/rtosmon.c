#include "rtosmon.h"
#include <string.h>

rtosmon_t g_rtosmon = { 0u, 0u, RTOSMON_NA, RTOSMON_NA, RTOSMON_NA, "", "", 0u, 0u, false, 0u };

static void copy_name(char *dst, const char *src)
{
    size_t i = 0;
    if (src) for (; i + 1u < RTOSMON_NAME_LEN && src[i]; i++) dst[i] = src[i];
    dst[i] = '\0';
}

void rtosmon_init(rtosmon_t *m)
{
    if (!m) return;
    memset(m, 0, sizeof *m);
    m->cpu_pm = m->stk_min_w = m->scan_min_w = RTOSMON_NA;
}

void rtosmon_feed_cpu(rtosmon_t *m, uint32_t idle, uint32_t total)
{
    if (!m) return;
    if (m->have_cpu) {
        uint32_t dt = total - m->last_total, di = idle - m->last_idle;   /* 无符号差：回绕安全 */
        if (dt > 0u) {
            if (di > dt) di = dt;   /* 两个计数不是同一瞬间读的，可能差一点 */
            m->cpu_pm = (uint16_t)(1000u - (uint32_t)(((uint64_t)di * 1000u + dt / 2u) / dt));
            m->samples++;
        }
    }
    m->last_idle = idle; m->last_total = total; m->have_cpu = true;
}

void rtosmon_begin_stack(rtosmon_t *m) { if (m) { m->scan_min_w = RTOSMON_NA; m->scan_n = 0u; m->scan_worst[0] = '\0'; } }

void rtosmon_feed_stack(rtosmon_t *m, const char *name, uint32_t free_words)
{
    if (!m) return;
    uint16_t w = free_words >= RTOSMON_NA ? (uint16_t)(RTOSMON_NA - 1u) : (uint16_t)free_words;
    if (m->scan_n < 255u) m->scan_n++;
    if (m->scan_min_w == RTOSMON_NA || w < m->scan_min_w) { m->scan_min_w = w; copy_name(m->scan_worst, name); }
}

void rtosmon_end_stack(rtosmon_t *m)
{
    if (!m || m->scan_n == 0u) return;
    m->stk_min_w = m->scan_min_w; m->n_tasks = m->scan_n;
    memcpy(m->worst, m->scan_worst, RTOSMON_NAME_LEN);
}

uint16_t rtosmon_cpu_permille(const rtosmon_t *m) { return m ? m->cpu_pm : RTOSMON_NA; }
uint16_t rtosmon_stack_min_words(const rtosmon_t *m) { return m ? m->stk_min_w : RTOSMON_NA; }
bool rtosmon_stack_low(const rtosmon_t *m, uint16_t thresh_words)
{
    return m && m->stk_min_w != RTOSMON_NA && m->stk_min_w < thresh_words;
}

dz_err_t rtosmon_selftest(void)
{
    rtosmon_t m;
    rtosmon_init(&m);
    if (rtosmon_cpu_permille(&m) != RTOSMON_NA || rtosmon_stack_low(&m, 32u)) return DZ_EFAIL;
    rtosmon_feed_cpu(&m, 0xFFFFFF00u, 0xFFFFFF00u);
    rtosmon_feed_cpu(&m, 0xFFFFFF00u + 750u, 0xFFFFFF00u + 1000u);   /* 跨 32 位回绕：25 % 负载 */
    if (m.cpu_pm != 250u) return DZ_EFAIL;
    rtosmon_begin_stack(&m);
    rtosmon_feed_stack(&m, "ctrl", 100u); rtosmon_feed_stack(&m, "link", 20u);
    rtosmon_end_stack(&m);
    if (m.stk_min_w != 20u || strcmp(m.worst, "link") != 0 || !rtosmon_stack_low(&m, 32u)) return DZ_EFAIL;
    return DZ_OK;
}
