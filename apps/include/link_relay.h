/**
 * @file link_relay.h
 * @brief 继电自整定帧（DATA 0x7C，调参“无初值一键起步”）的唯一处理：link_app.h、car_2wd、2026H io_link 共用。
 *
 *   if (link_relay_frame(&f, estop_now, &seq, &ack)) send(&ack);   // 收帧循环里，急停判断之后
 *   link_relay_guard(estop_now);                                    // 每个主循环拍：急停/故障中立即结束继电
 */
#ifndef LINK_RELAY_H
#define LINK_RELAY_H
#include <stdbool.h>
#include "dzframe.h"
#include "dzctl.h"
#include "pid.h"

#ifndef LINK_RELAY_EN
#define LINK_RELAY_EN 1   /**< link.yaml `relay: off` → link_gen.h 定义为 0：0x7C 一律回 status 1，不接管输出 */
#endif

/** 是继电帧就处理并填 ack（status 0=ok 1=参数错/无此环 2=急停中拒绝），返回 true；否则 false。 */
static inline bool link_relay_frame(const dzframe_t *f, bool estop, uint8_t *seq, dzframe_t *ack)
{
    dzctl_relay_t rl;
    if (!dzctl_relay_parse(f, &rl)) return false;
    uint8_t s = 0u;
    if (!LINK_RELAY_EN) s = 1u;
    else if (!rl.start) { if (rl.amp < 0.0f) s = 1u; else pid_relay_stop(); }
    else if (estop) s = 2u;
    else if (pid_relay_start(rl.loop, rl.amp, rl.hyst, rl.timeout_s) != DZ_OK) s = 1u;
    dzctl_relay_ack(s, (*seq)++, ack);
    return true;
}

static inline void link_relay_guard(bool estop) { if (estop && pid_relay_active()) pid_relay_stop(); }
#endif
