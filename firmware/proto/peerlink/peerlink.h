/**
 * @file peerlink.h
 * @brief 两车/车机之间的状态链路（走 dzframe，任何串口无线模块：LoRa、蓝牙透传、ESP-NOW 桥…）。
 *
 * 发方每 period 发一帧 STATE（DATA id 0x70，26 字节）：u32 t_ms, f32 s_m（沿路径里程）, f32 v_mps, f32 x_m, f32 y_m, f32 yaw_rad, u16 flags。
 * 急停/任务中止：ABORT（DATA id 0x71，len 2：u16 reason），连发 3 帧；本地先停车再发，不等对方确认。
 * 收方：CRC 由 dzframe 保证；seq 不前进的帧（重复/乱序，差值不在 1..127）丢弃并计数；超过 stale_ms 没新帧 = 链路断。
 * 思路来自 DS-land-and-air（2026 电赛 D 题）的 LoRa 联调规范：固定时隙、新鲜度/CRC/长度/乱序检查、中止三帧且不延迟关电机。
 * Source: github.com/2026-nuedc-d-land-air/DS-land-and-air@0cec55c docs/D题_V23_联调与计分矩阵.md（用户确认可用，见 docs/参考来源.md）。
 * 版本：PEERLINK_VERSION
 */
#ifndef PEERLINK_H
#define PEERLINK_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "dzframe.h"
#define PEERLINK_VERSION "1.0.0"
#define PEERLINK_ID_STATE 0x70u
#define PEERLINK_ID_ABORT 0x71u
#define PEERLINK_STATE_LEN 26u

#define PEER_F_RUNNING 0x0001u   /**< 发方在任务中 */
#define PEER_F_MARK    0x0002u   /**< 发方刚过标记点（路口/停车线），收方据此同步 */
#define PEER_F_STOPPED 0x0004u   /**< 发方已停车 */

typedef struct {
    uint32_t t_ms;
    float s_m, v_mps, x_m, y_m, yaw_rad;
    uint16_t flags;
} peer_state_t;

typedef struct {
    uint32_t stale_ms;
    peer_state_t last;
    bool have, aborted;
    uint16_t abort_reason;
    uint8_t last_seq;
    uint32_t rx_ms;            /**< 本地收到最后一帧 STATE 的时间 */
    uint32_t good, dup_ooo, bad_len;
} peer_rx_t;

/** 打包一帧 STATE / ABORT（seq 由调用方的发送函数填）。 */
void peerlink_state_frame(const peer_state_t *s, dzframe_t *out);
void peerlink_abort_frame(uint16_t reason, dzframe_t *out);

void peer_rx_init(peer_rx_t *r, uint32_t stale_ms);
/** 喂一帧（不是本模块的帧返回 false，交给别的处理）。 */
bool peer_rx_feed(peer_rx_t *r, const dzframe_t *f, uint32_t now_ms);
/** 有新鲜的对方状态（收到过、没超时、没中止）。 */
bool peer_rx_fresh(const peer_rx_t *r, uint32_t now_ms);
uint32_t peer_rx_age_ms(const peer_rx_t *r, uint32_t now_ms);
/** 人确认后解除中止锁存。 */
void peer_rx_clear_abort(peer_rx_t *r);
dz_err_t peerlink_selftest(void);
#endif
