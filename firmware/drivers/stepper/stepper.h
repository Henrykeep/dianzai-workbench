/**
 * @file stepper.h
 * @brief 步进电机 STEP/DIR（A4988/DRV8825/TMC2209 独立模式/TB6600，42 步进），梯形加减速，整数相位累加器。
 *
 * 用法：固定频率定时器中断（tick_hz，典型 20 kHz）里调 stepper_tick()；主循环调 stepper_move_to()。
 *  - 速度用 Q32 相位增量 inc 表示：每 tick 相位 += inc，溢出一次走一步 → 步频 = inc·tick_hz/2³²。
 *  - 每 tick inc 改变 ainc（= 加速度·2³²/tick_hz²），刹车距离 d = inc²/(2·ainc·2³²) 步。
 *  - 剩余步数 ≤ d 就减速；方向相反的新目标先减到 0 再换向（DIR 改完至少隔一个 tick 才出脉冲）。
 *  - STEP 高电平保持 1 个 tick（20 kHz → 50 us，满足 A4988 ≥1 us、TB6600 ≥2.5 us），所以 max_sps ≤ tick_hz/2。
 * 无 float、无除法在 ISR 里（只有一次 64 位乘法和移位）。
 * 版本：STEPPER_VERSION
 */
#ifndef STEPPER_H
#define STEPPER_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "pal.h"
#define STEPPER_VERSION "1.0.0"

typedef struct {
    pal_id_t step, dir, en;   /**< gpio；en 可为 PAL_ID_NONE（多数驱动板 EN 低有效，board.yaml 配 active_low） */
    bool     invert_dir;
    uint32_t tick_hz;         /**< stepper_tick 调用频率 */
    uint32_t max_sps;         /**< 最大步频（步/秒，含细分） */
    uint32_t start_sps;       /**< 起跳/收尾最低步频，典型 200；不能为 0 */
    uint32_t acc_sps2;        /**< 加速度（步/秒²） */
} stepper_cfg_t;

typedef struct {
    stepper_cfg_t cfg;
    volatile int32_t pos, target;
    volatile uint32_t inc;
    uint32_t phase, ainc, vmax_inc, vmin_inc;
    int8_t dir;               /**< 当前 DIR 脚方向 ±1 */
    bool pulse_high, dir_settle, enabled, ready;
    volatile bool halt;
} stepper_t;

stepper_cfg_t stepper_cfg_default(pal_id_t step, pal_id_t dir, pal_id_t en);
dz_err_t stepper_init(stepper_t *s, const stepper_cfg_t *cfg);
dz_err_t stepper_enable(stepper_t *s, bool on);
dz_err_t stepper_move_to(stepper_t *s, int32_t target);
dz_err_t stepper_move_rel(stepper_t *s, int32_t delta);
/** 按加速度减速停下（停在当前位置 + 刹车距离）。 */
dz_err_t stepper_stop(stepper_t *s);
/** 立即停止脉冲（急停；高速时会丢步，之后要重新回零）。 */
dz_err_t stepper_halt(stepper_t *s);
/** 把当前位置定义为 pos（回零后调用）。只在静止时允许。 */
dz_err_t stepper_set_pos(stepper_t *s, int32_t pos);
/** [ISR] 固定频率调用。 */
void stepper_tick(stepper_t *s);
int32_t stepper_pos(const stepper_t *s);
bool stepper_busy(const stepper_t *s);
uint32_t stepper_speed_sps(const stepper_t *s);
/** 刹车距离（步），纯函数。 */
uint32_t stepper_stop_steps(uint32_t inc, uint32_t ainc);
dz_err_t stepper_selftest(void);
#endif
