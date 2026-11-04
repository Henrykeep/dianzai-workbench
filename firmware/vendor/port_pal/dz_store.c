/* 掉电保存参数 + 事件日志：FlashDB（armink/FlashDB，Apache-2.0，原样）+ FAL 设备 = pal_nvm。见 dz_store.h。 */
#include <string.h>
#include "dz_store.h"
#include "pal.h"
#include <flashdb.h>
#include <fal.h>

static int nvm_init(void);
static int nvm_read(long off, uint8_t *buf, size_t n);
static int nvm_write(long off, const uint8_t *buf, size_t n);
static int nvm_erase(long off, size_t n);
struct fal_flash_dev dz_pal_nvm_flash = { "pal_nvm", 0, 0, 1024, { nvm_init, nvm_read, nvm_write, nvm_erase }, 64 };

static int nvm_init(void)
{
    uint32_t size = 0, unit = 0;
    if (pal_nvm_info(&size, &unit) != DZ_OK || !unit) return -1;
    dz_pal_nvm_flash.len = size; dz_pal_nvm_flash.blk_size = unit;
    return 0;
}
static int nvm_read(long off, uint8_t *buf, size_t n) { return pal_nvm_read((uint32_t)off, buf, (uint32_t)n) == DZ_OK ? (int)n : -1; }
static int nvm_write(long off, const uint8_t *buf, size_t n)
{
    /* FlashDB 按 FDB_WRITE_GRAN=64 写，偶有不足 8 字节的尾巴：补 0xFF（flash 写 1 不改变位）凑成 8 字节对齐 */
    uint8_t tmp[8];
    uint32_t o = (uint32_t)off, head = o & 7u, done = 0;
    if (!head && !(n & 7u)) return pal_nvm_write(o, buf, (uint32_t)n) == DZ_OK ? (int)n : -1;
    while (done < n) {
        uint32_t a = (o + done) & ~7u, s = (o + done) - a, k = 8u - s;
        if (k > n - done) k = (uint32_t)(n - done);
        memset(tmp, 0xFF, sizeof tmp); memcpy(tmp + s, buf + done, k);
        if (pal_nvm_write(a, tmp, 8) != DZ_OK) return -1;
        done += k;
    }
    return (int)n;
}
static int nvm_erase(long off, size_t n)
{
    uint32_t u = (uint32_t)dz_pal_nvm_flash.blk_size, a = (uint32_t)off / u * u, e = ((uint32_t)off + (uint32_t)n + u - 1) / u * u;
    return pal_nvm_erase(a, e - a) == DZ_OK ? (int)n : -1;
}

static struct fdb_kvdb s_kv;
static struct fdb_tsdb s_ts;
static int s_ok;
static fdb_time_t now_ms(void) { return (fdb_time_t)pal_millis(); }

dz_err_t dz_store_init(void)
{
    uint32_t size = 0, unit = 0;
    s_ok = 0;
    if (pal_nvm_info(&size, &unit) != DZ_OK) return DZ_ENOTSUP;
    if (size < DZ_STORE_KV_SIZE + DZ_STORE_TS_SIZE || DZ_STORE_KV_SIZE < 2 * unit || DZ_STORE_TS_SIZE < 2 * unit) return DZ_EINVAL;
    if (fal_init() < 0) return DZ_EIO;
    memset(&s_kv, 0, sizeof s_kv); memset(&s_ts, 0, sizeof s_ts);
    uint32_t sec = unit;
    fdb_kvdb_control(&s_kv, FDB_KVDB_CTRL_SET_SEC_SIZE, &sec);
    if (fdb_kvdb_init(&s_kv, "param", "dz_kv", NULL, NULL) != FDB_NO_ERR) return DZ_EIO;
    fdb_tsdb_control(&s_ts, FDB_TSDB_CTRL_SET_SEC_SIZE, &sec);
    if (fdb_tsdb_init(&s_ts, "event", "dz_ts", now_ms, DZ_EVENT_MAX, NULL) != FDB_NO_ERR) return DZ_EIO;
    s_ok = 1;
    return DZ_OK;
}

dz_err_t dz_param_save(const char *key, const void *val, size_t len)
{
    struct fdb_blob b;
    if (!s_ok) return DZ_ENOTSUP;
    return fdb_kv_set_blob(&s_kv, key, fdb_blob_make(&b, val, len)) == FDB_NO_ERR ? DZ_OK : DZ_EIO;
}
size_t dz_param_load(const char *key, void *val, size_t len)
{
    struct fdb_blob b;
    if (!s_ok) return 0;
    return fdb_kv_get_blob(&s_kv, key, fdb_blob_make(&b, val, len));
}
dz_err_t dz_param_erase(const char *key)
{
    if (!s_ok) return DZ_ENOTSUP;
    return fdb_kv_del(&s_kv, key) == FDB_NO_ERR ? DZ_OK : DZ_EIO;
}

dz_err_t dz_event_log(const char *text)
{
    struct fdb_blob b;
    size_t n = strlen(text);
    if (!s_ok) return DZ_ENOTSUP;
    if (n > DZ_EVENT_MAX - 1) n = DZ_EVENT_MAX - 1;
    return fdb_tsl_append(&s_ts, fdb_blob_make(&b, text, n)) == FDB_NO_ERR ? DZ_OK : DZ_EIO;
}

struct iter_ctx { dz_event_cb_t cb; void *ctx; uint32_t n; };
static bool iter_one(fdb_tsl_t tsl, void *arg)
{
    struct iter_ctx *c = (struct iter_ctx *)arg;
    struct fdb_blob b;
    char buf[DZ_EVENT_MAX];
    size_t n = tsl->log_len < sizeof buf - 1 ? tsl->log_len : sizeof buf - 1;
    n = fdb_blob_read((fdb_db_t)&s_ts, fdb_tsl_to_blob(tsl, fdb_blob_make(&b, buf, n)));
    buf[n] = 0;
    c->n++;
    return c->cb && c->cb((uint32_t)tsl->time, buf, c->ctx) != 0;
}
uint32_t dz_event_iter(dz_event_cb_t cb, void *ctx)
{
    struct iter_ctx c = { cb, ctx, 0 };
    if (s_ok) fdb_tsl_iter(&s_ts, iter_one, &c);
    return c.n;
}
dz_err_t dz_event_clear(void)
{
    if (!s_ok) return DZ_ENOTSUP;
    fdb_tsl_clean(&s_ts);
    return DZ_OK;
}
