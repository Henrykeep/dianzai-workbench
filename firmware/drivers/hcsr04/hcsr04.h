/**
 * @file hcsr04.h
 * @brief HC-SR04 超声波测距：10 us 触发 + 回波脉宽计时，非阻塞。只依赖 pal.h。
 *
 * 两种回波采集方式：
 *  - 外部中断：ECHO 引脚双边沿中断里调用 hcsr04_echo_edge(level, pal_micros())（精度 ~1 us）；
 *  - 轮询：周期调用 hcsr04_poll()，它读 ECHO 电平自己找边沿（精度 = 轮询周期，100 us 轮询 ≈ 17 mm）。
 * 距离 = 脉宽 × 声速 / 2，声速 c = 331.3 + 0.606·T(°C) m/s（干燥空气近似）。
 * 两次测量间隔 ≥ 60 ms（模块手册建议，防上一次回波串扰）。无回波（> timeout）报 HCSR04_TIMEOUT。
 * 版本：HCSR04_VERSION
 */
#ifndef HCSR04_H
#define HCSR04_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "pal.h"
#define HCSR04_VERSION "1.0.0"

typedef enum { HCSR04_IDLE = 0, HCSR04_WAIT_RISE, HCSR04_WAIT_FALL, HCSR04_DONE, HCSR04_TIMEOUT } hcsr04_phase_t;

typedef struct {
    pal_id_t trig, echo;      /**< gpio：TRIG 输出，ECHO 输入（5 V 模块的 ECHO 要分压到 3.3 V！） */
    uint32_t period_ms;       /**< 自动测量周期，≥ 60 */
    uint32_t timeout_us;      /**< 典型 25000（≈4.3 m） */
    uint16_t min_mm, max_mm;  /**< 有效量程，典型 20 / 4000 */
} hcsr04_cfg_t;

typedef struct {
    hcsr04_cfg_t cfg;
    volatile hcsr04_phase_t phase;
    volatile uint32_t t_trig, t_rise, width_us;
    bool last_level;
    uint32_t last_start_ms;
    float c_mm_per_us;
    float dist_mm;
    bool valid, ready, started;
} hcsr04_t;

hcsr04_cfg_t hcsr04_cfg_default(pal_id_t trig, pal_id_t echo);
dz_err_t hcsr04_init(hcsr04_t *h, const hcsr04_cfg_t *cfg);
/** 设气温（°C，-20..60），更新声速。 */
dz_err_t hcsr04_set_temp(hcsr04_t *h, float temp_c);
/** 立即发 10 us 触发脉冲（阻塞 10 us）。上一次还没结束返回 DZ_EBUSY。 */
dz_err_t hcsr04_trigger(hcsr04_t *h, uint32_t now_us);
/** 回波边沿（ISR 里调用）。[ISR-safe] */
void hcsr04_echo_edge(hcsr04_t *h, bool level, uint32_t now_us);
/** 轮询：读 ECHO 电平找边沿 + 处理超时。中断模式也要调它（只做超时处理）。 */
dz_err_t hcsr04_poll(hcsr04_t *h, uint32_t now_us, bool read_pin);
/** 一站式：到周期自动触发 + poll；有新结果返回 true。 */
bool hcsr04_update(hcsr04_t *h, uint32_t now_ms, uint32_t now_us, bool read_pin);
/** 脉宽 → 毫米（纯函数）。 */
float hcsr04_width_to_mm(const hcsr04_t *h, uint32_t width_us);
bool hcsr04_valid(const hcsr04_t *h);
float hcsr04_mm(const hcsr04_t *h);
dz_err_t hcsr04_selftest(void);
#endif
