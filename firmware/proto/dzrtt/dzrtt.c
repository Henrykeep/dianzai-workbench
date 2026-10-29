#include "dzrtt.h"
#include <string.h>

#if defined(__GNUC__)
#define DZRTT_BARRIER() __asm__ volatile("" ::: "memory")   /* Cortex-M0+/M4 单核：编译器屏障即可（RAM 无缓存） */
#else
#define DZRTT_BARRIER()
#endif

dzrtt_cb_t g_dzrtt;
static char s_up[DZRTT_UP_SIZE], s_down[DZRTT_DOWN_SIZE];
static volatile uint8_t s_ready;

void dzrtt_init(void)
{
    if (s_ready) return;
    dzrtt_cb_t *c = &g_dzrtt;
    c->max_up = 1; c->max_down = 1;
    c->up[0] = (dzrtt_ring_t){ "Terminal", s_up, DZRTT_UP_SIZE, 0, 0, 0 };        /* flags 0 = 满了丢（非阻塞） */
    c->down[0] = (dzrtt_ring_t){ "Terminal", s_down, DZRTT_DOWN_SIZE, 0, 0, 0 };
    DZRTT_BARRIER();
    /* ID 最后写、分两段写：镜像里不出现完整 ID 字符串，探针不会误把 .rodata 里的常量当控制块 */
    memcpy(&c->id[7], "RTT", 4);
    DZRTT_BARRIER();
    memcpy(&c->id[0], "SEGGER ", 7);
    DZRTT_BARRIER();
    s_ready = 1;
}

dz_err_t dzrtt_write(const uint8_t *buf, uint16_t len)
{
    if (!buf && len) return DZ_EINVAL;
    dzrtt_init();
    dzrtt_ring_t *r = &g_dzrtt.up[0];
    uint32_t wr = r->wr, rd = r->rd;
    uint32_t free_ = (rd > wr) ? rd - wr - 1u : r->size - (wr - rd) - 1u;
    if (len > free_) return DZ_EBUSY;
    for (uint16_t i = 0; i < len; i++) {
        r->buf[wr] = (char)buf[i];
        if (++wr == r->size) wr = 0;
    }
    DZRTT_BARRIER();
    r->wr = wr;                                 /* 数据先落地，再挪写指针 */
    return DZ_OK;
}

dz_err_t dzrtt_read(uint8_t *buf, uint16_t max, uint16_t *got)
{
    if (!buf || !got) return DZ_EINVAL;
    dzrtt_init();
    dzrtt_ring_t *r = &g_dzrtt.down[0];
    uint32_t wr = r->wr, rd = r->rd;
    uint16_t n = 0;
    DZRTT_BARRIER();
    while (rd != wr && n < max) {
        buf[n++] = (uint8_t)r->buf[rd];
        if (++rd == r->size) rd = 0;
    }
    DZRTT_BARRIER();
    r->rd = rd;
    *got = n;
    return DZ_OK;
}

int dzrtt_selftest(void)
{
    dzrtt_init();
    return (memcmp(g_dzrtt.id, "SEGGER RTT", 11) == 0 && g_dzrtt.up[0].size == DZRTT_UP_SIZE) ? 0 : -1;
}
