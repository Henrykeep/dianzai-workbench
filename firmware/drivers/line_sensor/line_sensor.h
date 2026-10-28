/**
 * @file line_sensor.h
 * @brief 灰度/红外循迹传感器阵列（1..8 路，数字 GPIO 或模拟 ADC），输出线位置（mm）+ 丢线/路口标志。
 *
 * 位置 = Σ wᵢ·xᵢ / Σ wᵢ，xᵢ = (i − (n−1)/2)·pitch_mm（i=0 在最左，左负右正），wᵢ = 归一化“像线程度”0..1。
 * 模拟通道先标定：在白底和黑线上各扫一遍，记每路 min/max；归一化 v = (raw−min)/(max−min)，
 * line_high=false 时取 1−v（看模块：多数 TCRT5000 板黑线读数高，部分灰度板相反）。
 * 丢线（Σw < lost_sum）：位置保持在最后看到的一侧的最外端，置 LINE_F_LOST，控制器据此原地找线。
 * 路口（同时“像线”的路数 ≥ cross_n）：置 LINE_F_CROSS，位置给 0（不让十字/T 字把车拽歪）。
 * 版本：LINE_SENSOR_VERSION
 */
#ifndef LINE_SENSOR_H
#define LINE_SENSOR_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "pal.h"
#define LINE_SENSOR_VERSION "1.0.0"
#define LINE_MAX_CH 8u

#define LINE_F_LOST  0x01u
#define LINE_F_CROSS 0x02u

typedef struct {
    uint8_t  n;                    /**< 通道数 1..8 */
    bool     analog;               /**< true = ids 是 adc 资源；false = gpio（active=看到线，极性在 board.yaml） */
    pal_id_t ids[LINE_MAX_CH];     /**< 左→右 */
    bool     line_high;            /**< 模拟：线上读数更大为 true */
    float    pitch_mm;             /**< 相邻探头间距，常见 10..20 */
    float    on_thr;               /**< 归一化后 ≥ 此值算“看到线”，典型 0.5 */
    float    lost_sum;             /**< Σw 低于此视为丢线，典型 0.3 */
    uint8_t  cross_n;              /**< ≥ 此路数同时看到线 = 路口；0 = 不检测 */
} line_cfg_t;

typedef struct {
    float   pos_mm;                /**< 左负右正 */
    float   strength;              /**< Σw */
    uint8_t mask;                  /**< bit i = 第 i 路看到线 */
    uint8_t flags;                 /**< LINE_F_* */
} line_result_t;

typedef struct {
    line_cfg_t cfg;
    uint16_t cmin[LINE_MAX_CH], cmax[LINE_MAX_CH];
    float last_pos;
    bool calibrating, calibrated, ready;
} line_sensor_t;

line_cfg_t line_cfg_default(void);
dz_err_t line_init(line_sensor_t *l, const line_cfg_t *cfg);
/** 标定：begin → 多次 feed（推着车在白底/黑线上来回扫）→ end。数字模式不需要。 */
dz_err_t line_calib_begin(line_sensor_t *l);
dz_err_t line_calib_feed(line_sensor_t *l);
dz_err_t line_calib_end(line_sensor_t *l);
/** 直接装入已存的标定值（掉电保存后用）。 */
dz_err_t line_calib_set(line_sensor_t *l, const uint16_t *cmin, const uint16_t *cmax);
/** 读全部通道并计算。 */
dz_err_t line_read(line_sensor_t *l, line_result_t *out);
/** 纯逻辑：输入归一化 w[n]（0..1）。 */
dz_err_t line_compute(line_sensor_t *l, const float *w, line_result_t *out);
dz_err_t line_sensor_selftest(void);
#endif
