/**
 * @file bmi088.h
 * @brief Bosch BMI088 六轴 IMU（SPI，加速度计和陀螺仪是两颗独立的芯片、各有一根片选）。RoboMaster C 型板板载。
 *
 * 寄存器按 Bosch《BMI088 Datasheet》BST-BMI088-DS001 Rev 1.9：
 *   加速度计：CHIP_ID 0x00=0x1E；上电默认处于 I2C 模式，CSB1 出现一次上升沿（即一次哑读）后切到 SPI；
 *             SPI 读要多读一个哑字节；SOFTRESET 0x7E=0xB6；PWR_CONF 0x7C=0（激活）；PWR_CTRL 0x7D=4（开启）；
 *             ACC_CONF 0x40；ACC_RANGE 0x41；数据从 0x12 起 6 字节（小端），温度在 0x22/0x23（11 位）。
 *   陀螺仪：CHIP_ID 0x00=0x0F；SOFTRESET 0x14=0xB6；RANGE 0x0F；BANDWIDTH 0x10；数据从 0x02 起 6 字节（小端）。
 * 一个 pal_spi id 对应一颗芯片（board.yaml 写两条共用总线的 spi 条目）。
 * 版本：BMI088_VERSION
 */
#ifndef BMI088_H
#define BMI088_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "pal.h"

#define BMI088_VERSION "1.0.0"

typedef enum { BMI088_ACC_3G = 0, BMI088_ACC_6G, BMI088_ACC_12G, BMI088_ACC_24G } bmi088_acc_range_t;
typedef enum { BMI088_GYR_2000 = 0, BMI088_GYR_1000, BMI088_GYR_500, BMI088_GYR_250, BMI088_GYR_125 } bmi088_gyr_range_t;

typedef struct {
    pal_id_t spi_acc, spi_gyr;
    bmi088_acc_range_t acc_range;
    bmi088_gyr_range_t gyr_range;
    uint8_t acc_conf;           /**< ACC_CONF：0xAB = normal 滤波、800 Hz ODR（约 140 Hz 带宽） */
    uint8_t gyr_bw;             /**< GYRO_BANDWIDTH：0x02 = 1000 Hz ODR、116 Hz 带宽 */
} bmi088_cfg_t;

typedef struct {
    bmi088_cfg_t cfg;
    float acc_scale, gyr_scale;  /**< raw → m/s²、raw → rad/s */
    float gyr_bias[3];
    bool ok;
    uint32_t errors;
} bmi088_t;

typedef struct { float acc[3]; float gyr[3]; float temp_c; bool acc_sat; } bmi088_data_t;

bmi088_cfg_t bmi088_cfg_default(pal_id_t spi_acc, pal_id_t spi_gyr);
/** 软复位两颗芯片 → 配置 → 读回校验。芯片 ID 不对返回 DZ_ENODEV（通常是片选接反或 SPI 模式不对）。阻塞约 60 ms。 */
dz_err_t bmi088_init(bmi088_t *d, const bmi088_cfg_t *cfg);
dz_err_t bmi088_read(bmi088_t *d, bmi088_data_t *out);
/** 读温度（约 1.28 s 才更新一次，不必每拍读）。 */
dz_err_t bmi088_read_temp(bmi088_t *d, float *temp_c);
dz_err_t bmi088_calib_gyro(bmi088_t *d, uint16_t n, uint32_t period_ms);
dz_err_t bmi088_selftest(void);   /**< 纯换算自检 */
#endif
