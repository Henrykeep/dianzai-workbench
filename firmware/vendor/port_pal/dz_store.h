/**
 * @file dz_store.h
 * @brief 掉电保存参数 + 板上事件日志：FlashDB（KVDB/TSDB）+ EasyLogger，经 FAL 落到 pal_nvm_*（任何实现了 PAL 1.9 掉电存储区的板子）。
 * 平台没有 nvm（pal_nvm_info 返回 DZ_ENOTSUP）或区太小 → dz_store_init 返回错误，其余接口返回 DZ_ENOTSUP，应用照常跑。
 * 不要在中断里调（flash 擦写阻塞）。
 */
#ifndef DZ_STORE_H
#define DZ_STORE_H
#include <stddef.h>
#include <stdint.h>
#include "dz_err.h"

dz_err_t dz_store_init(void);
/** 参数：任意二进制值按名字存取（掉电不丢）。get 返回实际读到的字节数，没有该键返回 0。 */
dz_err_t dz_param_save(const char *key, const void *val, size_t len);
size_t   dz_param_load(const char *key, void *val, size_t len);
dz_err_t dz_param_erase(const char *key);
/** 事件日志：一条文本（截到 DZ_EVENT_MAX 字节），带 pal_millis 时间戳；满了覆盖最旧。 */
#define DZ_EVENT_MAX 96
dz_err_t dz_event_log(const char *text);
/** 从旧到新遍历；cb 返回 非 0 停止。返回遍历条数。 */
typedef int (*dz_event_cb_t)(uint32_t t_ms, const char *text, void *ctx);
uint32_t dz_event_iter(dz_event_cb_t cb, void *ctx);
dz_err_t dz_event_clear(void);
/** EasyLogger 输出钩子（elog_port.c 调）：每行日志先给它（例如写调试串口），WARN 以上同时进事件日志。 */
typedef void (*dz_log_sink_t)(const char *line, size_t len);
void dz_log_set_sink(dz_log_sink_t sink);
#endif
