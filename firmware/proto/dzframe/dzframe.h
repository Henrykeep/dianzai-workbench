/**
 * @file dzframe.h
 * @brief 统一帧协议 dzframe/1：主控 ↔ 协处理板（Jetson Nano、FPGA、另一块 MCU）之间唯一的通信格式。
 *
 * 帧格式（所有多字节数都是小端）：
 *
 *   | 0xA5 | 0x5A | VER=1 | KIND | ID | SEQ | LEN | PAYLOAD[LEN] | CRC16_L | CRC16_H |
 *
 *   KIND：DZF_DATA 数据通道（ID = board.yaml 中 channels[].id）
 *         DZF_PARAM_SET / DZF_PARAM_ACK 参数读写（ID = params[].id）
 *         DZF_HEARTBEAT 心跳（ID=0，LEN=0）
 *   CRC16：CRC-16/CCITT-FALSE（多项式 0x1021，初值 0xFFFF），覆盖 VER..PAYLOAD。
 *   LEN ≤ DZFRAME_MAX_PAYLOAD。
 *
 * 纯 C、无硬件依赖、无动态内存、可重入（每个链路一个解析器实例），Python 端实现见 tools/dzframe.py。
 * 版本：DZFRAME_VERSION（与同目录 VERSION 一致）。
 */
#ifndef DZFRAME_H
#define DZFRAME_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#define DZFRAME_VERSION "1.0.0"
#define DZFRAME_PROTO_VER 1u
#define DZFRAME_MAX_PAYLOAD 64u
#define DZFRAME_OVERHEAD 9u          /**< 2 SOF + VER + KIND + ID + SEQ + LEN + 2 CRC */
#define DZFRAME_MAX_FRAME (DZFRAME_MAX_PAYLOAD + DZFRAME_OVERHEAD)

typedef enum { DZF_DATA = 0, DZF_PARAM_SET = 1, DZF_PARAM_ACK = 2, DZF_HEARTBEAT = 3 } dzframe_kind_t;

typedef struct {
    uint8_t kind;
    uint8_t id;
    uint8_t seq;
    uint8_t len;
    uint8_t payload[DZFRAME_MAX_PAYLOAD];
} dzframe_t;

typedef struct {
    uint8_t  buf[DZFRAME_MAX_FRAME];
    uint16_t n;            /**< buf 中已有字节数 */
    uint32_t good;         /**< 正确帧计数 */
    uint32_t bad;          /**< CRC 错、版本错、长度非法的次数 */
} dzframe_parser_t;

/** CRC-16/CCITT-FALSE。 */
uint16_t dzframe_crc16(const uint8_t *data, size_t len);

/** 把 f 编码到 out；返回帧长度，cap 不够或 len 非法时返回 0。 */
size_t dzframe_encode(uint8_t *out, size_t cap, const dzframe_t *f);

void dzframe_parser_init(dzframe_parser_t *p);

/**
 * 喂一个字节；凑满一帧且校验正确时把帧写入 out 并返回 true。
 * 出错时自动在已缓存的字节里重新寻找帧头（不会因为一个坏帧丢掉紧跟其后的好帧）。
 */
bool dzframe_feed(dzframe_parser_t *p, uint8_t byte, dzframe_t *out);

/* 负载读写小工具（小端，越界时 put 返回 false、get 返回 0）。 */
bool dzframe_put_u8 (dzframe_t *f, uint8_t v);
bool dzframe_put_u16(dzframe_t *f, uint16_t v);
bool dzframe_put_u32(dzframe_t *f, uint32_t v);
bool dzframe_put_f32(dzframe_t *f, float v);
uint8_t  dzframe_get_u8 (const dzframe_t *f, size_t off);
uint16_t dzframe_get_u16(const dzframe_t *f, size_t off);
uint32_t dzframe_get_u32(const dzframe_t *f, size_t off);
float    dzframe_get_f32(const dzframe_t *f, size_t off);

#endif
