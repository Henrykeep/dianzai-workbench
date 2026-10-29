/**
 * 2026H 底盘安全：两路堵转（负载 = 占空比，没有电流采样）+ 异常复位安全态 + 黑匣子。
 * 通用件在 firmware/framework/safety；本文件只放门限。门限与 car_2wd 默认一致，[未测] 实车。
 */
#include "io_safety.h"
#include <stddef.h>
#include "safety.h"

#define STALL_DUTY      0.6f    /* 占空比 ≥ 0.6 */
#define STALL_SPEED_RPS 0.05f   /* 且轮转速 < 0.05 r/s */
#define STALL_HOLD_MS   500u    /* 持续 0.5 s 算堵转 */
#define STALL_IGNORE_MS 300u    /* 起步 0.3 s 豁免 */

static safety_t s_safe;
static bb_t s_bb;
static bb_rec_t s_ring[32];

bool io_safety_init(uint32_t reset_cause, uint32_t now_ms)
{
    stall_cfg_t c = { .load_on = STALL_DUTY, .speed_on = STALL_SPEED_RPS, .hold_ms = STALL_HOLD_MS,
                      .start_ignore_ms = STALL_IGNORE_MS, .retry_ms = 0u };
    (void)bb_init(&s_bb, s_ring, (uint16_t)(sizeof s_ring / sizeof s_ring[0]), NULL);
    if (safety_init(&s_safe, &c, 2u, &s_bb) != DZ_OK) return false;
    return safety_boot(&s_safe, reset_cause, reset_cause == 4u || reset_cause == 6u, now_ms);   /* = PAL_RESET_IS_FAULT */
}

bool io_safety_step(float cmd_a, float cmd_b, float rps_a, float rps_b, uint32_t now_ms)
{
    bool a = safety_update(&s_safe, 0u, cmd_a, rps_a, now_ms);
    bool b = safety_update(&s_safe, 1u, cmd_b, rps_b, now_ms);
    return a || b || safety_latched(&s_safe);
}

void io_safety_clear(uint32_t now_ms) { safety_clear(&s_safe, now_ms); }
bool io_safety_latched(void) { return safety_latched(&s_safe); }
uint32_t io_safety_flags(void) { return safety_flags(&s_safe); }
const bb_t *io_safety_bb(void) { return &s_bb; }
