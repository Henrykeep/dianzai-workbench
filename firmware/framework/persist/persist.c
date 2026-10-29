/* 掉电保存，见 persist.h。 */
#include <string.h>
#include "persist.h"

typedef struct { uint32_t magic; uint16_t key, len; uint32_t seq, crc; } rec_hdr_t;   /* 16 字节 */

static uint32_t crc32(uint32_t c, const void *p, uint32_t n)
{
    const uint8_t *b = (const uint8_t *)p;
    while (n--) { c ^= *b++; for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1u))); }
    return c;
}
static uint32_t pad8(uint32_t n) { return (n + 7u) & ~7u; }
static uint32_t rec_crc(const rec_hdr_t *h, const void *d)
{
    uint32_t c = crc32(0xFFFFFFFFu, &h->key, 8u);           /* key、len、seq */
    return ~crc32(c, d, h->len);
}

static dz_err_t fail(persist_kv_t *kv, dz_err_t e)
{
    kv->errors++;
    if (++kv->fails >= PERSIST_MAX_FAIL) kv->usable = false;
    return e;
}

static dz_err_t rd(persist_kv_t *kv, uint8_t bank, uint32_t off, void *p, uint32_t n)
{
    return kv->f.read(kv->f.ctx, kv->f.base + bank * kv->bank_size + off, p, n);
}

/* 扫一个 bank：返回写入点 tail 和最大 seq；坏记录（魔数在但 CRC 错）按长度跳过，长度离谱则停（之后视为满）。 */
static void scan(persist_kv_t *kv, uint8_t bank, uint32_t *tail, uint32_t *maxseq, bool *any)
{
    uint8_t d[PERSIST_MAX_LEN];
    uint32_t off = 0;
    *maxseq = 0; *any = false;
    while (off + sizeof(rec_hdr_t) <= kv->bank_size) {
        rec_hdr_t h;
        if (rd(kv, bank, off, &h, sizeof h) != DZ_OK) { off = kv->bank_size; break; }
        if (h.magic == 0xFFFFFFFFu && h.key == 0xFFFFu) break;                  /* 擦过的空白：写入点 */
        if (h.magic != PERSIST_MAGIC || h.len > PERSIST_MAX_LEN || off + sizeof h + pad8(h.len) > kv->bank_size) {
            off = kv->bank_size; break;                                         /* 不认识：剩下的当满 */
        }
        if (rd(kv, bank, off + sizeof h, d, h.len) == DZ_OK && rec_crc(&h, d) == h.crc) {
            *any = true;
            if (h.seq > *maxseq) *maxseq = h.seq;
        }
        off += sizeof h + pad8(h.len);
    }
    *tail = off;
}

dz_err_t persist_kv_init(persist_kv_t *kv, const persist_flash_t *f)
{
    uint32_t t0, t1, s0, s1;
    bool a0, a1;
    if (!kv || !f || !f->erase || !f->write || !f->read || !f->unit) return DZ_EINVAL;
    memset(kv, 0, sizeof *kv);
    kv->f = *f;
    kv->bank_size = (f->size / 2u) / f->unit * f->unit;
    if (kv->bank_size < f->unit || kv->bank_size < 64u) return DZ_EINVAL;
    kv->usable = true;
    scan(kv, 0, &t0, &s0, &a0);
    scan(kv, 1, &t1, &s1, &a1);
    kv->active = (a1 && (!a0 || s1 > s0)) ? 1u : 0u;
    kv->tail = kv->active ? t1 : t0;
    kv->seq = s0 > s1 ? s0 : s1;
    return DZ_OK;
}

bool persist_kv_usable(const persist_kv_t *kv) { return kv && kv->usable; }

/* 在 bank 里找 key 的最新有效记录，返回其数据偏移（0 = 没有） */
static uint32_t find(persist_kv_t *kv, uint8_t bank, uint32_t limit, uint16_t key, rec_hdr_t *out, uint8_t *d)
{
    uint32_t off = 0, hit = 0;
    rec_hdr_t h;
    while (off + sizeof h <= limit) {
        if (rd(kv, bank, off, &h, sizeof h) != DZ_OK || h.magic != PERSIST_MAGIC || h.len > PERSIST_MAX_LEN) break;
        if (h.key == key && rd(kv, bank, off + sizeof h, d, h.len) == DZ_OK && rec_crc(&h, d) == h.crc) {
            *out = h; hit = off + (uint32_t)sizeof h;
        }
        off += sizeof h + pad8(h.len);
    }
    if (hit) (void)rd(kv, bank, hit, d, out->len);
    return hit;
}

dz_err_t persist_kv_get(persist_kv_t *kv, uint16_t key, void *buf, uint16_t max, uint16_t *len)
{
    uint8_t d[PERSIST_MAX_LEN];
    rec_hdr_t h;
    if (len) *len = 0;
    if (!kv || !buf) return DZ_EINVAL;
    if (!kv->usable) return DZ_ENOTSUP;
    if (!find(kv, kv->active, kv->tail, key, &h, d)) return DZ_EFAIL;
    memcpy(buf, d, h.len < max ? h.len : max);
    if (len) *len = h.len;
    return DZ_OK;
}

static dz_err_t append(persist_kv_t *kv, uint8_t bank, uint32_t *tail, uint16_t key, const void *data, uint16_t len)
{
    uint8_t blk[PERSIST_MAX_LEN + 8u];
    rec_hdr_t h = { PERSIST_MAGIC, key, len, ++kv->seq, 0 };
    uint32_t addr = kv->f.base + bank * kv->bank_size + *tail;
    h.crc = rec_crc(&h, data);
    memset(blk, 0xFF, sizeof blk);
    memcpy(blk, data, len);
    /* 先写头再写数据：写到一半掉电 = 头在、CRC 对不上，扫描按长度跳过（不会把半截数据区当空白再写一遍） */
    *tail += sizeof h + pad8(len);
    if (kv->f.write(kv->f.ctx, addr, &h, sizeof h) != DZ_OK) return DZ_EIO;
    if (len && kv->f.write(kv->f.ctx, addr + sizeof h, blk, pad8(len)) != DZ_OK) return DZ_EIO;
    return DZ_OK;
}

dz_err_t persist_kv_put(persist_kv_t *kv, uint16_t key, const void *data, uint16_t len)
{
    uint8_t d[PERSIST_MAX_LEN];
    rec_hdr_t h;
    uint32_t need = sizeof(rec_hdr_t) + pad8(len);
    if (!kv || (!data && len) || len > PERSIST_MAX_LEN || key == 0xFFFFu) return DZ_EINVAL;
    if (!kv->usable) return DZ_ENOTSUP;
    if (find(kv, kv->active, kv->tail, key, &h, d) && h.len == len && !memcmp(d, data, len)) return DZ_OK;   /* 没变：不写 */
    if (kv->tail + need <= kv->bank_size) {
        if (append(kv, kv->active, &kv->tail, key, data, len) != DZ_OK) return fail(kv, DZ_EIO);
        kv->fails = 0;
        return DZ_OK;
    }
    {   /* 搬家：擦另一个 bank，搬每个 key 的最新值（跳过本 key），再写新值，最后切过去 */
        uint8_t nb = (uint8_t)(kv->active ^ 1u);
        uint16_t keys[PERSIST_MAX_KEYS]; uint8_t nk = 0, i;
        uint32_t off = 0, nt = 0;
        while (off + sizeof h <= kv->tail) {
            if (rd(kv, kv->active, off, &h, sizeof h) != DZ_OK || h.magic != PERSIST_MAGIC || h.len > PERSIST_MAX_LEN) break;
            bool seen = h.key == key;
            for (i = 0; i < nk && !seen; i++) seen = keys[i] == h.key;
            if (!seen && nk < PERSIST_MAX_KEYS) keys[nk++] = h.key;
            off += sizeof h + pad8(h.len);
        }
        if (kv->f.erase(kv->f.ctx, kv->f.base + nb * kv->bank_size, kv->bank_size) != DZ_OK) return fail(kv, DZ_EIO);
        for (i = 0; i < nk; i++) {
            if (!find(kv, kv->active, kv->tail, keys[i], &h, d)) continue;
            if (nt + sizeof h + pad8(h.len) + need > kv->bank_size) return fail(kv, DZ_EFAIL);
            if (append(kv, nb, &nt, keys[i], d, h.len) != DZ_OK) return fail(kv, DZ_EIO);
        }
        if (nt + need > kv->bank_size) return fail(kv, DZ_EFAIL);
        if (append(kv, nb, &nt, key, data, len) != DZ_OK) return fail(kv, DZ_EIO);
        kv->active = nb; kv->tail = nt; kv->compactions++; kv->fails = 0;
        return DZ_OK;
    }
}

/* ---- 黑匣子冻结区 ---- */
static dz_err_t bb_erase(void *ctx) { const persist_flash_t *f = ctx; return f->erase(f->ctx, f->base, f->size / f->unit * f->unit); }
static dz_err_t bb_write(void *ctx, uint32_t off, const void *p, uint32_t n)
{
    const persist_flash_t *f = ctx;
    uint8_t tail[8];
    uint32_t whole = n & ~7u;
    if (off % 8u) return DZ_EINVAL;
    if (whole && f->write(f->ctx, f->base + off, p, whole) != DZ_OK) return DZ_EIO;
    if (n > whole) {                                                     /* 不足 8 字节的尾巴：补 0xFF */
        memset(tail, 0xFF, sizeof tail);
        memcpy(tail, (const uint8_t *)p + whole, n - whole);
        if (f->write(f->ctx, f->base + off + whole, tail, 8u) != DZ_OK) return DZ_EIO;
    }
    return DZ_OK;
}
static dz_err_t bb_read(void *ctx, uint32_t off, void *p, uint32_t n) { const persist_flash_t *f = ctx; return f->read(f->ctx, f->base + off, p, n); }

dz_err_t persist_bb_store(bb_store_t *out, const persist_flash_t *f)
{
    if (!out || !f || !f->unit || f->size < f->unit) return DZ_EINVAL;
    out->erase = bb_erase; out->write = bb_write; out->read = bb_read;
    out->ctx = (void *)f; out->size = f->size / f->unit * f->unit;
    return DZ_OK;
}

/* ---- 自测：RAM 假 flash（NOR 语义 + 故障注入） ---- */
typedef struct { uint8_t m[2048]; int fail_at; int ops; uint32_t erases; } ram_t;
static dz_err_t r_erase(void *c, uint32_t off, uint32_t n) { ram_t *r = c; if (++r->ops == r->fail_at) return DZ_EIO; memset(r->m + off, 0xFF, n); r->erases++; return DZ_OK; }
static dz_err_t r_write(void *c, uint32_t off, const void *p, uint32_t n)
{
    ram_t *r = c; const uint8_t *b = p;
    if (++r->ops == r->fail_at) return DZ_EIO;
    for (uint32_t i = 0; i < n; i++) r->m[off + i] &= b[i];
    return DZ_OK;
}
static dz_err_t r_read(void *c, uint32_t off, void *p, uint32_t n) { ram_t *r = c; memcpy(p, r->m + off, n); return DZ_OK; }

dz_err_t persist_selftest(void)
{
    static ram_t r;
    persist_flash_t f = { r_erase, r_write, r_read, &r, 0u, 2048u, 512u };
    persist_kv_t kv;
    uint32_t v = 0, i;
    uint16_t n;
    int fail = 0;
    memset(&r, 0xFF, sizeof r.m); r.fail_at = 0; r.ops = 0; r.erases = 0;
    fail += persist_kv_init(&kv, &f) != DZ_OK || persist_kv_get(&kv, 1, &v, 4, &n) != DZ_EFAIL;   /* 空片 */
    for (i = 1; i <= 200u; i++) fail += persist_kv_put(&kv, 1, &i, 4) != DZ_OK;                   /* 反复写：会搬家 */
    v = 7u; fail += persist_kv_put(&kv, 2, &v, 4) != DZ_OK;
    fail += persist_kv_init(&kv, &f) != DZ_OK;                                                     /* “重新上电” */
    fail += persist_kv_get(&kv, 1, &v, 4, &n) != DZ_OK || v != 200u || n != 4u;
    fail += persist_kv_get(&kv, 2, &v, 4, &n) != DZ_OK || v != 7u;
    fail += r.erases > 20u;                                                                        /* 200 次写只擦了少数几次 */
    i = r.erases; v = 7u; (void)persist_kv_put(&kv, 2, &v, 4); fail += r.erases != i || kv.tail == 0;   /* 同值不写 */
    r.fail_at = r.ops + 2; v = 300u;                                                               /* 写数据那步失败 = 掉电 */
    fail += persist_kv_put(&kv, 1, &v, 4) != DZ_EIO;
    fail += persist_kv_init(&kv, &f) != DZ_OK || persist_kv_get(&kv, 1, &v, 4, &n) != DZ_OK || v != 200u;   /* 旧值还在 */
    v = 301u; fail += persist_kv_put(&kv, 1, &v, 4) != DZ_OK;                                     /* 跳过半截记录继续写 */
    fail += persist_kv_init(&kv, &f) != DZ_OK || persist_kv_get(&kv, 1, &v, 4, &n) != DZ_OK || v != 301u;
    r.fail_at = -1;
    {   /* 连续失败 → 停用，不挡调用方 */
        ram_t *rr = &r; int k;
        for (k = 0; k < 3; k++) { rr->fail_at = rr->ops + 1; v = 400u + (uint32_t)k; (void)persist_kv_put(&kv, 1, &v, 4); }
        fail += persist_kv_usable(&kv) || persist_kv_put(&kv, 1, &v, 4) != DZ_ENOTSUP;
    }
    f.size = 64u; fail += persist_kv_init(&kv, &f) != DZ_EINVAL;
    return fail ? DZ_EINVAL : DZ_OK;
}
