/**
 * @file mpu6050.h
 * @brief InvenSense MPU-6050 六轴 IMU（I2C），经 PAL I2C 读写。也兼容 WHO_AM_I=0x70/0x71 的 MPU-6500/9250 的加速度/陀螺部分。
 *
 * 寄存器与换算按《MPU-6000/MPU-6050 Register Map and Descriptions Rev 4.2》（RM-MPU-6000A-00）：
 *   PWR_MGMT_1 0x6B、SMPLRT_DIV 0x19、CONFIG 0x1A（DLPF）、GYRO_CONFIG 0x1B、ACCEL_CONFIG 0x1C、
 *   ACCEL_XOUT_H 0x3B 起 14 字节（加速度 6 + 温度 2 + 陀螺 6，大端）、WHO_AM_I 0x75 = 0x68。
 * 只用逻辑资源 id（board.yaml 的 i2c 条目），换板只改 board.yaml。
 * 版本：MPU6050_VERSION
 */
#ifndef MPU6050_H
#define MPU6050_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "pal.h"

#define MPU6050_VERSION "1.0.0"
#define MPU6050_ADDR_LO 0x68u   /**< AD0 接地 */
#define MPU6050_ADDR_HI 0x69u   /**< AD0 接 VCC */

typedef enum { MPU6050_ACC_2G = 0, MPU6050_ACC_4G, MPU6050_ACC_8G, MPU6050_ACC_16G } mpu6050_acc_fs_t;
typedef enum { MPU6050_GYR_250 = 0, MPU6050_GYR_500, MPU6050_GYR_1000, MPU6050_GYR_2000 } mpu6050_gyr_fs_t;

typedef struct {
    pal_id_t i2c;
    uint8_t addr;               /**< 0x68 / 0x69 */
    mpu6050_acc_fs_t acc_fs;
    mpu6050_gyr_fs_t gyr_fs;
    uint8_t dlpf;               /**< CONFIG.DLPF_CFG 0..6：3 = 加速度 44 Hz / 陀螺 42 Hz 带宽，1 kHz 内部采样 */
    uint8_t smplrt_div;         /**< 输出率 = 1 kHz / (1 + div)（DLPF 开启时） */
} mpu6050_cfg_t;

typedef struct {
    mpu6050_cfg_t cfg;
    float acc_lsb, gyr_lsb;     /**< LSB per g / LSB per °/s */
    float gyr_bias[3];          /**< rad/s，mpu6050_calib_gyro 填写 */
    uint8_t who;
    bool ok;
    uint32_t errors;
} mpu6050_t;

typedef struct { float acc[3]; float gyr[3]; float temp_c; bool acc_sat; } mpu6050_data_t;  /**< m/s²、rad/s（已减零偏） */

mpu6050_cfg_t mpu6050_cfg_default(pal_id_t i2c);
/** 复位 → 唤醒（PLL 时钟）→ 配量程/DLPF/输出率 → 读回校验。WHO_AM_I 不对返回 DZ_ENODEV。阻塞约 110 ms。 */
dz_err_t mpu6050_init(mpu6050_t *d, const mpu6050_cfg_t *cfg);
/** 一次突发读 14 字节并换算。失败计数 errors++，返回 PAL 错误码。 */
dz_err_t mpu6050_read(mpu6050_t *d, mpu6050_data_t *out);
/** 静止时取 n 次陀螺平均作零偏（每次间隔 period_ms）。任一读失败返回错误且不改原零偏。 */
dz_err_t mpu6050_calib_gyro(mpu6050_t *d, uint16_t n, uint32_t period_ms);
dz_err_t mpu6050_selftest(void);   /**< 纯换算自检（不碰总线） */
#endif
