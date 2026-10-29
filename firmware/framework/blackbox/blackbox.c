/**
 * @file blackbox.c
 * @brief 见 blackbox.h。思路来源：DS-land-and-air（队友工程）的冻结日志 F 命令与 ESP32 NVS 写满卡启动的教训（docs/参考来源.md）；代码自写。
 */
#include "blackbox.h"
#include <stdio.h>
#include <string.h>

typedef struct { uint32_t magic, n, crc, rsv; } bb_hdr_t;

static uint32_t crc_upd(uint32_t c, const void *p, uint32_t n)      /* CRC-32（IEEE），c 初值 0xFFFFFFFF，结果取反 */
{
    const uint8_t *b = (const uint8_t *)p;
    while (n--) { c ^= *b++; for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1u))); }
    return c;
}

dz_err_t bb_init(bb_t *bb, bb_rec_t *buf, uint16_t cap, const bb_store_t *store)
{
    if (!bb || !buf || cap == 0u) return DZ_EINVAL;
    memset(bb, 0, sizeof *bb);
    bb->ring = buf; bb->cap = cap;
    bb->st = (store && store->erase && store->write && store->read && store->size >= sizeof(bb_hdr_t) + sizeof(bb_rec_t)) ? store : NULL;
    return DZ_OK;
}

void bb_log(bb_t *bb, uint32_t t_ms, uint16_t code, uint16_t arg, float a, float b)
{
    if (!bb || !bb->ring) return;
    bb_rec_t *r = &bb->ring[bb->head];
    r->t_ms = t_ms; r->code = code; r->arg = arg; r->a = a; r->b = b;
    bb->head = (uint16_t)((bb->head + 1u) % bb->cap);
    bb->total++;
}

uint16_t bb_count(const bb_t *bb) { return !bb || !bb->ring ? 0u : bb->total < bb->cap ? (uint16_t)bb->total : bb->cap; }

const bb_rec_t *bb_get(const bb_t *bb, uint16_t i)
{
    uint16_t n = bb_count(bb);
    if (i >= n) return NULL;
    uint16_t first = (uint16_t)((bb->head + bb->cap - n) % bb->cap);
    return &bb->ring[(first + i) % bb->cap];
}

bool bb_store_usable(const bb_t *bb) { return bb && bb->st && bb->st_fail < BB_STORE_MAX_FAIL; }

static dz_err_t fail(bb_t *bb) { bb->st_errors++; if (bb->st_fail < BB_STORE_MAX_FAIL) bb->st_fail++; return DZ_EIO; }

dz_err_t bb_freeze(bb_t *bb)
{
    if (!bb_store_usable(bb)) return DZ_ENOTSUP;
    uint16_t n = bb_count(bb);
    uint32_t fit = (bb->st->size - (uint32_t)sizeof(bb_hdr_t)) / (uint32_t)sizeof(bb_rec_t);
    uint16_t skip = n > fit ? (uint16_t)(n - fit) : 0u;          /* 放不下：只存最新的 */
    n = (uint16_t)(n - skip);
    /* 环可能回绕：拼成连续块再写，保证最多 1 擦 + 2 写。分两段写记录、头最后写（头有效 = 记录写完）。 */
    bb_hdr_t h = { BB_MAGIC, n, 0xFFFFFFFFu, 0u };
    uint16_t first = (uint16_t)((bb->head + bb->cap - bb_count(bb) + skip) % bb->cap);
    uint16_t seg1 = (uint16_t)((first + n <= bb->cap) ? n : bb->cap - first);
    uint32_t c = crc_upd(0xFFFFFFFFu, &bb->ring[first], (uint32_t)seg1 * sizeof(bb_rec_t));
    c = crc_upd(c, &bb->ring[0], (uint32_t)(n - seg1) * sizeof(bb_rec_t));
    h.crc = ~c;
    if (bb->st->erase(bb->st->ctx) != DZ_OK) return fail(bb);
    uint32_t off = sizeof h;
    if (seg1 && bb->st->write(bb->st->ctx, off, &bb->ring[first], (uint32_t)seg1 * sizeof(bb_rec_t)) != DZ_OK) return fail(bb);
    off += (uint32_t)seg1 * sizeof(bb_rec_t);
    if (n > seg1 && bb->st->write(bb->st->ctx, off, &bb->ring[0], (uint32_t)(n - seg1) * sizeof(bb_rec_t)) != DZ_OK) return fail(bb);
    if (bb->st->write(bb->st->ctx, 0u, &h, sizeof h) != DZ_OK) return fail(bb);
    bb->st_fail = 0u;
    return DZ_OK;
}

dz_err_t bb_load_frozen(bb_t *bb, bb_rec_t *out, uint16_t max, uint16_t *n)
{
    if (n) *n = 0u;
    if (!out || !n) return DZ_EINVAL;
    if (!bb_store_usable(bb)) return DZ_ENOTSUP;
    bb_hdr_t h;
    if (bb->st->read(bb->st->ctx, 0u, &h, sizeof h) != DZ_OK) return fail(bb);
    uint32_t fit = (bb->st->size - (uint32_t)sizeof h) / (uint32_t)sizeof(bb_rec_t);
    if (h.magic != BB_MAGIC || h.n > fit) return DZ_EFAIL;     /* 从没写过 / 擦了没写完：不算存储故障 */
    if (h.n > max) return DZ_EINVAL;                              /* 调用方缓冲太小：不截断，免得 crc 对不上被当成坏数据 */
    uint16_t k = (uint16_t)h.n;
    if (k && bb->st->read(bb->st->ctx, sizeof h, out, (uint32_t)k * sizeof(bb_rec_t)) != DZ_OK) return fail(bb);
    if (~crc_upd(0xFFFFFFFFu, out, (uint32_t)k * sizeof(bb_rec_t)) != h.crc) return DZ_EFAIL;
    bb->st_fail = 0u;
    *n = k;
    return DZ_OK;
}

uint16_t bb_dump(const bb_rec_t *r, uint16_t n, void (*put)(void *ctx, const char *line), void *ctx)
{
    char line[64];
    if (!r || !put) return 0u;
    for (uint16_t i = 0; i < n; i++) {
        snprintf(line, sizeof line, "BB,%lu,%u,%u,%.4g,%.4g\n", (unsigned long)r[i].t_ms, (unsigned)r[i].code,
                 (unsigned)r[i].arg, (double)r[i].a, (double)r[i].b);
        put(ctx, line);
    }
    return n;
}

/* ---- 自检：内存模拟存储 ---- */
typedef struct { uint8_t mem[16u + 4u * 16u]; int fail_erase, fail_write; int ops; } fake_t;
static dz_err_t f_erase(void *c) { fake_t *f = c; f->ops++; if (f->fail_erase) return DZ_EIO; memset(f->mem, 0xFF, sizeof f->mem); return DZ_OK; }
static dz_err_t f_write(void *c, uint32_t o, const void *p, uint32_t n)
{ fake_t *f = c; f->ops++; if (f->fail_write || o + n > sizeof f->mem) return DZ_EIO; memcpy(f->mem + o, p, n); return DZ_OK; }
static dz_err_t f_read(void *c, uint32_t o, void *p, uint32_t n)
{ fake_t *f = c; f->ops++; if (o + n > sizeof f->mem) return DZ_EIO; memcpy(p, f->mem + o, n); return DZ_OK; }

dz_err_t bb_selftest(void)
{
    static fake_t f; bb_rec_t ring[6], out[4]; bb_t bb; uint16_t n;
    memset(&f, 0, sizeof f); memset(f.mem, 0xFF, sizeof f.mem);
    bb_store_t st = { f_erase, f_write, f_read, &f, sizeof f.mem };
    if (bb_init(&bb, ring, 6u, &st) != DZ_OK || f.ops != 0) return DZ_EFAIL;          /* init 不碰存储 */
    if (bb_load_frozen(&bb, out, 4u, &n) != DZ_EFAIL) return DZ_EFAIL;                 /* 空区 */
    for (uint32_t i = 0; i < 9u; i++) bb_log(&bb, i * 10u, (uint16_t)i, 0u, 0.0f, 0.0f);
    if (bb_count(&bb) != 6u || bb_get(&bb, 0)->code != 3u) return DZ_EFAIL;
    if (bb_freeze(&bb) != DZ_OK || bb_load_frozen(&bb, out, 4u, &n) != DZ_OK || n != 4u
        || out[0].code != 5u || out[3].code != 8u) return DZ_EFAIL;                    /* 放 4 条：存最新 */
    return DZ_OK;
}
