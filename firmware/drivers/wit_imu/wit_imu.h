/**
 * @file wit_imu.h
 * @brief 维特智能（WIT）串口姿态模块：JY61P / JY901 / HWT101 的标准协议解析 + 非阻塞偏航清零。
 *
 * 帧：0x55 TYPE D0..D7 SUM（11 字节，SUM = 前 10 字节和的低 8 位），数据小端 int16。
 *   0x51 加速度  a = raw/32768*16 g      0x52 角速度 w = raw/32768*2000 °/s
 *   0x53 角度    roll/pitch/yaw = raw/32768*180 °（HWT101 只有 yaw 在 D4..D5，与 JY 系同位）
 *   0x54 磁场    raw（JY901）
 * 偏航清零：解锁 FF AA 69 88 B5 → 清零命令 → 保存 FF AA 00 00 00，命令间隔 gap_ms（非阻塞，wit_poll 推进）。
 *   JY61P/JY901 清零 = FF AA 01 04 00；HWT101 = FF AA 76 00 00。
 * 参考：ti-contest wit_jyxx.c、DS-land-and-air wit_c_sdk / bsp_gyro_wit（见 docs/参考来源.md）。
 * 版本：WIT_IMU_VERSION
 */
#ifndef WIT_IMU_H
#define WIT_IMU_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "pal.h"
#define WIT_IMU_VERSION "1.0.0"

typedef enum { WIT_JY61P = 0, WIT_JY901 = 1, WIT_HWT101 = 2 } wit_model_t;

typedef struct {
    pal_id_t uart;
    wit_model_t model;
    uint16_t gap_ms;        /**< 配置命令间隔，典型 100 */
    uint16_t stale_ms;      /**< 超过这么久没收到角度帧 = 失联，典型 100 */
} wit_cfg_t;

typedef struct {
    float acc_g[3], gyro_dps[3], roll, pitch, yaw;
    int16_t mag[3];
    uint32_t t_angle_ms;    /**< 最近一次角度帧时刻 */
    bool has_angle;
} wit_data_t;

typedef struct {
    wit_cfg_t cfg;
    wit_data_t d;
    uint8_t buf[11], n;
    uint32_t frames, bad_sum;
    uint8_t zstep;          /**< 0 空闲，1..3 清零流程第几条 */
    uint32_t znext;
    bool ready;
} wit_t;

dz_err_t wit_init(wit_t *w, const wit_cfg_t *cfg);
/** 收字节解帧并推进清零流程；返回本次新收到的有效帧数。 */
uint16_t wit_poll(wit_t *w, uint32_t now_ms);
/** 直接喂字节（DMA/中断回调用，或测试）；返回解出的有效帧数。 */
uint16_t wit_feed(wit_t *w, const uint8_t *p, uint16_t n, uint32_t now_ms);
const wit_data_t *wit_data(const wit_t *w);
/** 角度新鲜：收到过角度帧且距今 ≤ stale_ms。 */
bool wit_fresh(const wit_t *w, uint32_t now_ms);
/** 开始偏航清零（静止时调用）。流程中再调返回 DZ_EBUSY。 */
dz_err_t wit_zero_yaw_start(wit_t *w, uint32_t now_ms);
bool wit_zero_busy(const wit_t *w);
dz_err_t wit_imu_selftest(void);
#endif
