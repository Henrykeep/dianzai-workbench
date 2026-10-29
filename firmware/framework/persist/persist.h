/**
 * @file persist.h
 * @brief 掉电保存：参数等小数据的键值存储（双区、追加写、均衡磨损）+ 给黑匣子用的固定冻结区。不含硬件代码。
 *
 * 存储由 persist_flash_t 描述（擦除单位、擦后才能写、按 8 字节写）；硬件版见 drivers/nvm_pal（走 pal_nvm_*）。
 *
 * 键值区（persist_kv_*）：区域对半分 A/B 两个 bank。每条记录 = 16 字节头（魔数、key、len、seq、CRC）+ 数据（补齐 8 字节），只追加。
 *  - 读：取当前 bank 里该 key 最后一条 CRC 正确的记录；写到一半掉电 → 那条 CRC 不对，自动用上一条（旧值）。
 *  - 写：和现有值一样就不写（省擦写次数）；当前 bank 满了 → 擦另一个 bank，把每个 key 的最新值搬过去再写新的（整个 bank 才擦一次 = 磨损均衡）。
 *  - 铁律：init 只读不写，失败也返回（应用用默认值继续跑）；连续失败 PERSIST_MAX_FAIL 次后停用，后续调用立即返回 DZ_ENOTSUP。
 * 冻结区（persist_bb_store）：把一段区域包成 blackbox 的 bb_store_t（bb_freeze 一次擦 + 两次写，头最后写）。
 * 1.1.0：persist_kv_bb_store（黑匣子冻结进键值区的一个 key，不再要独立擦除单位：F4 16 KB 扇区也只要 2 个）；
 *        persist_blob_load/save（带结构哈希的整块参数，结构变了 → 不加载，用默认值）。
 * 版本：PERSIST_VERSION
 */
#ifndef PERSIST_H
#define PERSIST_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "blackbox.h"
#include "dz_flash.h"
#define PERSIST_VERSION "1.1.0"
#define PERSIST_MAX_FAIL 3u
#define PERSIST_MAX_KEYS 16u
#define PERSIST_MAX_LEN  256u
#define PERSIST_MAGIC    0x314B5644u   /* "DVK1" */



typedef struct {
    persist_flash_t f;
    uint32_t bank_size;
    uint8_t active;                /**< 0/1 */
    uint32_t tail;                 /**< 当前 bank 内下一个可写偏移 */
    uint32_t seq;                  /**< 最大 seq */
    bool usable;
    uint8_t fails;
    uint32_t errors, compactions;
} persist_kv_t;

/** 扫描两个 bank 定位当前 bank 与写入点。区域太小（每 bank < 1 个擦除单位或 < 64 字节）→ DZ_EINVAL。只读。 */
dz_err_t persist_kv_init(persist_kv_t *kv, const persist_flash_t *f);
/** 读最新值；*len = 实际长度（max 不够时只拷 max 字节）。没有这个 key → DZ_EFAIL。 */
dz_err_t persist_kv_get(persist_kv_t *kv, uint16_t key, void *buf, uint16_t max, uint16_t *len);
/** 写（len ≤ PERSIST_MAX_LEN，key ≠ 0xFFFF）。相同值不写。 */
dz_err_t persist_kv_put(persist_kv_t *kv, uint16_t key, const void *data, uint16_t len);
bool persist_kv_usable(const persist_kv_t *kv);

/** 把 f 描述的整段区域（黑匣子专用，别和键值区重叠）包成 bb_store_t。f 必须一直有效（out 只存指针）。 */
dz_err_t persist_bb_store(bb_store_t *out, const persist_flash_t *f);

/** 黑匣子存进键值区 key（最多 (PERSIST_MAX_LEN-16)/16 = 15 条）。bb_freeze 写头（off 0）那一下才真正落 flash，一次冻结 = 一次 put。 */
typedef struct { persist_kv_t *kv; uint16_t key; uint8_t buf[PERSIST_MAX_LEN]; } persist_kvbb_t;
dz_err_t persist_kv_bb_store(bb_store_t *out, persist_kvbb_t *ctx, persist_kv_t *kv, uint16_t key);

/** 整块参数：存 [hash u32][len 字节]。load 时 hash 或长度对不上 → DZ_EFAIL，p 不动（调用方保持默认值）。 */
dz_err_t persist_blob_save(persist_kv_t *kv, uint16_t key, uint32_t hash, const void *p, uint16_t len);
dz_err_t persist_blob_load(persist_kv_t *kv, uint16_t key, uint32_t hash, void *p, uint16_t len);
dz_err_t persist_selftest(void);
#endif
