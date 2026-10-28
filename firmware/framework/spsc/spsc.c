#include "spsc.h"
#include <string.h>
#include "dz_compiler.h"

dz_err_t spsc_init(spsc_t *q, void *storage, uint16_t elem_size, uint16_t cap)
{
    if (!q || !storage || elem_size == 0u || cap == 0u || (cap & (cap - 1u)) != 0u) return DZ_EINVAL;
    q->buf = (uint8_t *)storage; q->elem_size = elem_size; q->cap = cap;
    q->head = 0u; q->tail = 0u; q->dropped = 0u;
    return DZ_OK;
}

uint32_t spsc_count(const spsc_t *q) { return q ? (uint32_t)(q->head - q->tail) : 0u; }

dz_err_t spsc_push(spsc_t *q, const void *elem)
{
    uint32_t h;
    if (!q || !elem || !q->buf) return DZ_EINVAL;
    h = q->head;
    if ((uint32_t)(h - q->tail) >= q->cap) { q->dropped++; return DZ_EBUSY; }
    memcpy(q->buf + (size_t)(h & (q->cap - 1u)) * q->elem_size, elem, q->elem_size);
    DZ_COMPILER_BARRIER();      /* 数据先落地，再发布 head */
    q->head = h + 1u;
    return DZ_OK;
}

bool spsc_pop(spsc_t *q, void *elem)
{
    uint32_t t;
    if (!q || !elem || !q->buf) return false;
    t = q->tail;
    if (t == q->head) return false;
    DZ_COMPILER_BARRIER();
    memcpy(elem, q->buf + (size_t)(t & (q->cap - 1u)) * q->elem_size, q->elem_size);
    DZ_COMPILER_BARRIER();      /* 拷完再释放槽位 */
    q->tail = t + 1u;
    return true;
}

bool spsc_pop_latest(spsc_t *q, void *elem)
{
    bool got = false;
    while (spsc_pop(q, elem)) got = true;
    return got;
}

dz_err_t spsc_selftest(void)
{
    uint32_t st[4], v = 0u, i;
    spsc_t q;
    if (spsc_init(&q, st, sizeof st[0], 3u) != DZ_EINVAL) return DZ_EFAIL;
    if (spsc_init(&q, st, sizeof st[0], 4u) != DZ_OK) return DZ_EFAIL;
    for (i = 0u; i < 5u; i++) (void)spsc_push(&q, &i);
    if (spsc_count(&q) != 4u || q.dropped != 1u) return DZ_EFAIL;
    if (!spsc_pop(&q, &v) || v != 0u) return DZ_EFAIL;
    if (!spsc_pop_latest(&q, &v) || v != 3u || spsc_count(&q) != 0u) return DZ_EFAIL;
    return spsc_pop(&q, &v) ? DZ_EFAIL : DZ_OK;
}
