#ifndef IO_SAFETY_H
#define IO_SAFETY_H
/** 2026H 底盘的堵转/异常复位安全态（照 car_2wd 接 framework/safety）。不碰硬件，host 测试可直接链接。 */
#include <stdbool.h>
#include <stdint.h>
#include "blackbox.h"
/** 返回 true = 上次是看门狗/锁死复位，进安全态等人确认。 */
bool io_safety_init(uint32_t reset_cause, uint32_t now_ms);
/** 运行态每拍调：cmd 为占空比（-1..1），rps 为轮转速。返回 true = 已锁存（调用方急停）。 */
bool io_safety_step(float cmd_a, float cmd_b, float rps_a, float rps_b, uint32_t now_ms);
void io_safety_clear(uint32_t now_ms);
bool io_safety_latched(void);
uint32_t io_safety_flags(void);
const bb_t *io_safety_bb(void);
#endif
