/**
 * @file safety.h
 * @brief 通用安全监视（纯逻辑，不碰硬件、不依赖 pal/dzctl）：多路堵转 + 异常复位安全态 + 写黑匣子，统一一个“锁存”。
 *
 * 应用接法（car_2wd、2026H_ball 是范例）：
 *   app_init:   safety_init(&S, &stall_cfg, 通道数, &bb); safety_boot(&S, pal_reset_cause(), PAL_RESET_IS_FAULT(rc), now)
 *               → 返回 true = 上次是看门狗/锁死复位，应用锁急停
 *   控制周期:   每路 if (safety_update(&S, ch, 负载, 转速, now)) 这路输出归零/刹车
 *   主循环:     safety_latched(&S) → 急停；心跳 dzctl_set_flags(safety_flags(&S) 对应位)
 *   人工解除:   safety_clear(&S, now)（收到 'R'）
 * 负载 = 电流（有采样时）或占空比（没有时），单位与 stall_cfg.load_on 一致。
 * 标志位与 dzctl 心跳 status 字同位（bit8 SAFE_BOOT、bit9 STALL），可直接 OR 进去。
 * 每个事件进黑匣子一条：BB_EV_RESET(arg=复位原因)、BB_EV_STALL(arg=通道, a=负载, b=转速)、BB_EV_CLEAR。
 * 版本：SAFETY_VERSION
 */
#ifndef SAFETY_H
#define SAFETY_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "stall.h"
#include "blackbox.h"
#define SAFETY_VERSION "1.0.0"
#define SAFETY_MAX_CH 4u
#define SAFETY_F_SAFE_BOOT (1u << 8)
#define SAFETY_F_STALL     (1u << 9)

typedef struct {
    stall_t ch[SAFETY_MAX_CH];
    uint8_t n;
    bb_t *bb;                       /**< 可为 NULL（不记） */
    volatile uint32_t flags;
    volatile uint8_t stalled_mask;  /**< 哪几路锁存了堵转 */
} safety_t;

/** nch 为 1..SAFETY_MAX_CH；门限非法 → DZ_EINVAL。 */
dz_err_t safety_init(safety_t *s, const stall_cfg_t *cfg, uint8_t nch, bb_t *bb);
/** 上电调一次：记复位原因；fault 为真（看门狗/锁死）→ 锁存 SAFE_BOOT 并返回 true。 */
bool safety_boot(safety_t *s, uint32_t reset_cause, bool fault, uint32_t now_ms);
/** 控制周期每路调一次；返回 true = 这一路已堵转锁存（输出必须关）。首次锁存时记黑匣子。 */
bool safety_update(safety_t *s, uint8_t ch, float load, float speed, uint32_t now_ms);
/** 调参：只改门限，不清锁存。 */
void safety_set_stall(safety_t *s, float load_on, uint32_t hold_ms);
bool safety_latched(const safety_t *s);
uint32_t safety_flags(const safety_t *s);
/** 人工解除：清所有堵转与 SAFE_BOOT（有锁存时记 BB_EV_CLEAR）。和 safety_update 不在同一上下文时调用方关中断。 */
void safety_clear(safety_t *s, uint32_t now_ms);
dz_err_t safety_selftest(void);
#endif
