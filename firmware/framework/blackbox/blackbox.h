/**
 * @file blackbox.h
 * @brief 黑匣子：RAM 环形事件日志（永远可用）+ 可选的掉电存储（冻结一份，复位后读回）。
 *
 * 用法：出事（急停、堵转、看门狗、丢球）时 bb_log 记事件；需要留证据时 bb_freeze 把环里的记录写进存储，
 * 下次上电 bb_load_frozen 读回，经 dzctl 命令 / 串口导出（bb_dump）。
 * 铁律：**存储失败永远不能挡住启动和控制**（DS-land-and-air ESP32 的教训：NVS 写满后启动被卡住）。
 *  - bb_init 不碰存储（不擦、不读、不重试），只记下回调；
 *  - bb_freeze / bb_load_frozen 每次调用的存储操作次数有上限（1 次擦 + 2 次写 / 2 次读），失败只记错误计数并返回错误码；
 *  - 连续失败 BB_STORE_MAX_FAIL 次后存储自动停用，之后的调用立即返回 DZ_ENOTSUP，RAM 日志照常；
 *  - 冻结区是固定大小、每次先擦后写：不会“写满”；放不下时只存最新的那部分。
 * 存储回调由移植层/应用提供（片内 flash 末页、外部 SPI flash、模拟 EEPROM 均可），本模块不含任何硬件代码。
 * 版本：BLACKBOX_VERSION
 */
#ifndef BLACKBOX_H
#define BLACKBOX_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#define BLACKBOX_VERSION "1.0.0"
#define BB_STORE_MAX_FAIL 3u
#define BB_MAGIC 0x31424244u       /**< "DBB1" */

typedef struct { uint32_t t_ms; uint16_t code; uint16_t arg; float a, b; } bb_rec_t;   /**< 16 字节 */

typedef struct {
    dz_err_t (*erase)(void *ctx);                                           /**< 擦整个冻结区 */
    dz_err_t (*write)(void *ctx, uint32_t off, const void *p, uint32_t n);
    dz_err_t (*read)(void *ctx, uint32_t off, void *p, uint32_t n);
    void *ctx;
    uint32_t size;                                                          /**< 冻结区字节数 */
} bb_store_t;

typedef struct {
    bb_rec_t *ring; uint16_t cap, head; uint32_t total;   /**< total：累计记了多少条（可大于 cap） */
    const bb_store_t *st;
    uint8_t st_fail;                                      /**< 连续失败次数；达到上限即停用 */
    uint32_t st_errors;                                   /**< 累计失败次数（遥测用） */
} bb_t;

/** 永不失败于存储：store 可为 NULL（只用 RAM）。buf/cap 为 0 时返回 DZ_EINVAL。 */
dz_err_t bb_init(bb_t *bb, bb_rec_t *buf, uint16_t cap, const bb_store_t *store);
/** O(1)，可在控制周期里调用（不在中断里与 freeze 并发）。 */
void bb_log(bb_t *bb, uint32_t t_ms, uint16_t code, uint16_t arg, float a, float b);
/** 环里现有条数（≤ cap）。i=0 为最旧。 */
uint16_t bb_count(const bb_t *bb);
const bb_rec_t *bb_get(const bb_t *bb, uint16_t i);
/** 把环写进存储（擦 + 头 + 记录）。返回 DZ_OK / DZ_EIO / DZ_ENOTSUP（无存储或已停用）。 */
dz_err_t bb_freeze(bb_t *bb);
/** 读回上次冻结的记录到 out（最多 max 条），*n 为条数。魔数/长度/校验不对 → DZ_EFAIL（区里是垃圾或从没写过）。 */
dz_err_t bb_load_frozen(bb_t *bb, bb_rec_t *out, uint16_t max, uint16_t *n);
bool bb_store_usable(const bb_t *bb);
/** 每条记录格式化一行 "BB,t_ms,code,arg,a,b\n" 交给 put（串口发送等）。返回行数。 */
uint16_t bb_dump(const bb_rec_t *r, uint16_t n, void (*put)(void *ctx, const char *line), void *ctx);
dz_err_t bb_selftest(void);
#endif
