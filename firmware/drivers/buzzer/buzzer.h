/**
 * @file buzzer.h
 * @brief 蜂鸣器节奏（开/关毫秒序列 + 重复次数 + 优先级），非阻塞，周期调用 buzzer_tick()。
 *
 * 两种接法：有源蜂鸣器用 GPIO（gpio 资源，pwm=PAL_ID_NONE）；无源蜂鸣器用 PWM（pwm 资源，
 * 频率在 board.yaml 配 2..4 kHz，响时 50% 占空比）。高优先级打断低优先级；同级新节奏替换旧的。
 * 版本：BUZZER_VERSION
 */
#ifndef BUZZER_H
#define BUZZER_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "pal.h"
#define BUZZER_VERSION "1.0.0"
#define BUZZER_MAX_STEPS 16u

/** 节奏：steps[0]=响 ms, steps[1]=停 ms, steps[2]=响 ms ...；n 个步（≤16）；repeat=0 表示一直循环；
 *  repeat≠1 时 n 必须为偶数（以“停”结尾）。 */
typedef struct {
    const uint16_t *steps;
    uint8_t n;
    uint8_t repeat;
    uint8_t prio;          /**< 越大越优先 */
} buzzer_pattern_t;

extern const buzzer_pattern_t BUZZER_BEEP;      /**< 短响 1 声（按键提示） */
extern const buzzer_pattern_t BUZZER_OK;        /**< 两声短响 */
extern const buzzer_pattern_t BUZZER_ERROR;     /**< 三声长响 */
extern const buzzer_pattern_t BUZZER_LOWBAT;    /**< 低电量：一直循环，慢 */
extern const buzzer_pattern_t BUZZER_ALARM;     /**< 急停/严重故障：一直循环，快，最高优先级 */

typedef struct {
    pal_id_t gpio, pwm;
    const buzzer_pattern_t *cur;
    uint8_t step, rep_done;
    uint32_t step_at;
    bool on, ready;
} buzzer_t;

dz_err_t buzzer_init(buzzer_t *b, pal_id_t gpio, pal_id_t pwm);
/** 播放节奏。被更高优先级占用时返回 DZ_EBUSY（不打断）。 */
dz_err_t buzzer_play(buzzer_t *b, const buzzer_pattern_t *p, uint32_t now_ms);
dz_err_t buzzer_stop(buzzer_t *b);
/** 推进节奏，建议 ≤10 ms 周期调用。 */
dz_err_t buzzer_tick(buzzer_t *b, uint32_t now_ms);
bool buzzer_busy(const buzzer_t *b);
bool buzzer_is_on(const buzzer_t *b);
dz_err_t buzzer_selftest(void);
#endif
