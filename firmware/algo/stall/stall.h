/**
 * @file stall.h
 * @brief 堵转检测（纯逻辑）：“负载高 + 速度近零 + 持续一段时间”→ 堵转。负载可以是电流/Iq，没有电流采样时用指令占空比。
 *
 * 为什么要软件判：FOC/电流环下堵转时电流被顶到限幅，但不一定超过硬件过流保护阈值，电机却一直发热
 * （MICU-auto-embedded control-safety-limits.md 检查项 2）。只靠硬件 OCP 防不住。
 *  - 起步豁免：从“负载低”到“负载高”之后 start_ignore_ms 内不判（起步浪涌）；
 *  - 滞回：进入要 load ≥ load_on 且 |speed| ≤ speed_on 持续 hold_ms；
 *  - 锁存：STALLED 之后一直报，直到 stall_clear()，或配置了 retry_ms 时到点自动回 NORMAL 重试一次（之后再堵再锁）；
 *  - 应用拿到 STALLED 后自己决定：输出归零/进 ESTOP/记黑匣子（本模块不碰硬件）。
 * 阈值是标定项：写清单位与来源（电机手册堵转电流 / 实测空载电流），留余量。
 * 版本：STALL_VERSION
 */
#ifndef STALL_H
#define STALL_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#define STALL_VERSION "1.0.0"

typedef struct {
    float load_on;            /**< 负载高门限（A 或占空比 0..1，取绝对值比较） */
    float speed_on;           /**< 速度近零门限（与 speed 同单位，取绝对值） */
    uint32_t hold_ms;         /**< 持续多久算堵转 */
    uint32_t start_ignore_ms; /**< 负载刚升高后的豁免时间 */
    uint32_t retry_ms;        /**< 0 = 只能 stall_clear 解除；>0 = 锁存这么久后自动重试 */
} stall_cfg_t;

typedef enum { STALL_NORMAL = 0, STALL_SUSPECT = 1, STALL_STALLED = 2 } stall_state_t;

typedef struct {
    stall_cfg_t c;
    stall_state_t st;
    bool loaded; uint32_t t_load, t_suspect, t_stalled;
    uint32_t count;           /**< 累计堵转次数 */
} stall_t;

/** 门限非法（负数、NaN、hold_ms=0）→ DZ_EINVAL。 */
dz_err_t stall_init(stall_t *s, const stall_cfg_t *c);
/** 每个控制周期调一次。load/speed 非有限值按“不可信”处理：不进入、也不解除。 */
stall_state_t stall_update(stall_t *s, float load, float speed, uint32_t now_ms);
void stall_clear(stall_t *s);
dz_err_t stall_selftest(void);
#endif
