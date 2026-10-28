/**
 * @file battery.h
 * @brief 电池电压（ADC + 分压）+ 低压告警（滞回 + 保持时间）+ 粗略电量百分比。只依赖 pal.h。
 *
 * 电压 = raw/(2^bits-1) * vref_mv * num/den。分压比优先取 cfg.div_num/div_den（非 0 时），
 * 否则用 pal_adc_info() 的 scale（board.yaml adc 的 scale 字段）。
 * 状态：NONE（未接电池/读数 < absent_mv）→ OK → LOW → CRIT；
 * 进入更差状态需持续 hold_ms，恢复需高出阈值 hyst_mv 且持续 hold_ms（防电机启动瞬间压降误报）。
 * 版本：BATTERY_VERSION
 */
#ifndef BATTERY_H
#define BATTERY_H
#include <stdint.h>
#include "dz_err.h"
#include "pal.h"
#define BATTERY_VERSION "1.0.0"

typedef enum { BAT_NONE = 0, BAT_OK, BAT_LOW, BAT_CRIT } battery_state_t;

typedef struct {
    pal_id_t adc;
    uint16_t div_num, div_den; /**< 例：100k/10k 分压 → 11/1；0/0 = 用 board.yaml */
    uint8_t  cells;            /**< 锂电串数（2S=2），用于百分比；0 = 不算百分比 */
    uint16_t low_mv, crit_mv;  /**< 整包阈值，2S 典型 7000 / 6600 */
    uint16_t hyst_mv;          /**< 典型 150 */
    uint16_t hold_ms;          /**< 典型 2000 */
    uint16_t absent_mv;        /**< 低于此视为未接，典型 1000 */
    float    lpf_tau_s;        /**< 一阶滤波时间常数，典型 0.5 */
} battery_cfg_t;

typedef struct {
    battery_cfg_t cfg;
    uint32_t num, den, full_code, vref_mv;
    float mv;
    battery_state_t state, cand;
    uint32_t cand_since, last_ms;
    uint8_t primed, ready;
} battery_t;

battery_cfg_t battery_cfg_default(pal_id_t adc);
dz_err_t battery_init(battery_t *b, const battery_cfg_t *cfg);
/** 读一次 ADC 并更新状态（建议 10..100 ms 周期）。 */
dz_err_t battery_update(battery_t *b, uint32_t now_ms);
/** 纯逻辑：喂原始码（便于测试）。 */
dz_err_t battery_feed_raw(battery_t *b, uint16_t raw, uint32_t now_ms);
float battery_mv(const battery_t *b);
battery_state_t battery_state(const battery_t *b);
/** 0..100，按单节 3.3..4.2 V 的锂电近似曲线（粗略，仅作显示）；cells=0 返回 -1。 */
int battery_percent(const battery_t *b);
const char *battery_state_name(battery_state_t s);
dz_err_t battery_selftest(void);
#endif
