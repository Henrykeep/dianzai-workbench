/**
 * @file as5600.h
 * @brief AS5600 12 位磁编码器（I2C 0x36，经 PAL）：原始角、多圈展开、速度（一阶低通）、磁铁状态。
 *
 * 寄存器：STATUS 0x0B（MD 磁铁在 bit5 / ML 太弱 bit4 / MH 太强 bit3）、RAW ANGLE 0x0C..0x0D（12 位，不受 ZPOS/MPOS 影响）、
 * AGC 0x1A、MAGNITUDE 0x1B..0x1C。只读 RAW ANGLE，零点 / 方向在软件里做（不烧 OTP）。
 * 400 kHz 下读 2 字节约 70 µs；FOC 电流环频率高时请把 as5600_update 放到较慢的任务里，FOC 用插值角度。
 * 参考：pid_helper STM32F1 / ESP32-C3 例程 as5600_dev.c（跨零修正、速度滤波思路）、SimpleFOC MagneticSensorI2C。
 * 版本：AS5600_VERSION
 */
#ifndef AS5600_H
#define AS5600_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "pal.h"
#define AS5600_VERSION "1.0.0"
#define AS5600_ADDR 0x36u

typedef struct {
    pal_id_t i2c;
    int8_t dir;            /**< +1 / -1：软件方向 */
    float vel_tau_s;       /**< 速度低通时间常数，0 = 不滤，典型 0.005 */
} as5600_cfg_t;

typedef struct {
    as5600_cfg_t cfg;
    uint16_t raw, zero;    /**< zero：软件零点（原始计数） */
    int32_t turns;
    float angle;           /**< 单圈 [0, 2π)，已减零点、乘方向 */
    float angle_multi;     /**< 多圈连续角（rad） */
    float vel;             /**< rad/s */
    uint32_t t_us;
    bool has, ready;
    uint32_t errors;
    uint8_t status;
} as5600_t;

dz_err_t as5600_init(as5600_t *e, const as5600_cfg_t *cfg);
/** 读磁铁状态：DZ_OK = 磁铁在且强度合适；DZ_ENODEV = 没检测到磁铁；DZ_EFAIL = 太弱 / 太强（*status 给原值）。 */
dz_err_t as5600_check_magnet(as5600_t *e, uint8_t *status);
/** 读一次角度并更新多圈 / 速度。now_us 用 pal_micros()。两次调用之间转过不能超过半圈。 */
dz_err_t as5600_update(as5600_t *e, uint32_t now_us);
/** 把当前位置设为零点（多圈清零）。 */
dz_err_t as5600_set_zero_here(as5600_t *e);
static inline float as5600_angle(const as5600_t *e) { return e->angle; }
static inline float as5600_angle_multi(const as5600_t *e) { return e->angle_multi; }
static inline float as5600_velocity(const as5600_t *e) { return e->vel; }
dz_err_t as5600_selftest(void);
#endif
