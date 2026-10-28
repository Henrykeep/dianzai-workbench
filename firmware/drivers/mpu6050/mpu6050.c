#include <math.h>
#include <string.h>
#include "mpu6050.h"

#define R_SMPLRT_DIV  0x19u
#define R_CONFIG      0x1Au
#define R_GYRO_CONFIG 0x1Bu
#define R_ACCEL_CONFIG 0x1Cu
#define R_INT_PIN_CFG 0x37u
#define R_ACCEL_XOUT_H 0x3Bu
#define R_PWR_MGMT_1  0x6Bu
#define R_WHO_AM_I    0x75u
#define G_MPS2  9.80665f
#define DEG2RAD 0.017453292519943295f

static const float ACC_LSB[4] = { 16384.0f, 8192.0f, 4096.0f, 2048.0f };
static const float GYR_LSB[4] = { 131.0f, 65.5f, 32.8f, 16.4f };

mpu6050_cfg_t mpu6050_cfg_default(pal_id_t i2c)
{
    return (mpu6050_cfg_t){ i2c, MPU6050_ADDR_LO, MPU6050_ACC_4G, MPU6050_GYR_1000, 3u, 0u };
}

static dz_err_t wr(mpu6050_t *d, uint8_t reg, uint8_t v) { return pal_i2c_mem_write(d->cfg.i2c, d->cfg.addr, reg, &v, 1u); }

dz_err_t mpu6050_init(mpu6050_t *d, const mpu6050_cfg_t *cfg)
{
    if (!d || !cfg || cfg->acc_fs > MPU6050_ACC_16G || cfg->gyr_fs > MPU6050_GYR_2000 || cfg->dlpf > 6u) return DZ_EINVAL;
    memset(d, 0, sizeof *d);
    d->cfg = *cfg;
    d->acc_lsb = ACC_LSB[cfg->acc_fs]; d->gyr_lsb = GYR_LSB[cfg->gyr_fs];
    dz_err_t e = pal_i2c_mem_read(cfg->i2c, cfg->addr, R_WHO_AM_I, &d->who, 1u);
    if (e) return e;
    if (d->who != 0x68u && d->who != 0x70u && d->who != 0x71u && d->who != 0x73u) return DZ_ENODEV;
    if ((e = wr(d, R_PWR_MGMT_1, 0x80u))) return e;        /* DEVICE_RESET */
    pal_delay_ms(100u);
    if ((e = wr(d, R_PWR_MGMT_1, 0x01u))) return e;        /* 退出睡眠，时钟 = X 轴陀螺 PLL（手册推荐，比内部 8 MHz RC 稳） */
    pal_delay_ms(10u);
    const uint8_t regs[4] = { R_SMPLRT_DIV, R_CONFIG, R_GYRO_CONFIG, R_ACCEL_CONFIG };
    const uint8_t vals[4] = { cfg->smplrt_div, cfg->dlpf, (uint8_t)(cfg->gyr_fs << 3), (uint8_t)(cfg->acc_fs << 3) };
    for (int i = 0; i < 4; i++) {
        uint8_t rb = 0xFFu;
        if ((e = wr(d, regs[i], vals[i]))) return e;
        if ((e = pal_i2c_mem_read(cfg->i2c, cfg->addr, regs[i], &rb, 1u))) return e;
        if (rb != vals[i]) return DZ_EIO;                  /* 写进去读回不一致：线太长/上拉不够/地址冲突 */
    }
    d->ok = true;
    return DZ_OK;
}

static int16_t be16(const uint8_t *p) { return (int16_t)(uint16_t)((uint16_t)p[0] << 8 | p[1]); }

static void convert(const mpu6050_t *d, const uint8_t raw[14], mpu6050_data_t *o)
{
    o->acc_sat = false;
    for (int i = 0; i < 3; i++) {
        int16_t a = be16(raw + 2 * i), g = be16(raw + 8 + 2 * i);
        if (a == INT16_MAX || a == INT16_MIN) o->acc_sat = true;
        o->acc[i] = (float)a / d->acc_lsb * G_MPS2;
        o->gyr[i] = (float)g / d->gyr_lsb * DEG2RAD - d->gyr_bias[i];
    }
    o->temp_c = (float)be16(raw + 6) / 340.0f + 36.53f;
}

dz_err_t mpu6050_read(mpu6050_t *d, mpu6050_data_t *out)
{
    uint8_t raw[14];
    if (!d || !out) return DZ_EINVAL;
    if (!d->ok) return DZ_ESTATE;
    dz_err_t e = pal_i2c_mem_read(d->cfg.i2c, d->cfg.addr, R_ACCEL_XOUT_H, raw, sizeof raw);
    if (e) { d->errors++; return e; }
    convert(d, raw, out);
    return DZ_OK;
}

dz_err_t mpu6050_calib_gyro(mpu6050_t *d, uint16_t n, uint32_t period_ms)
{
    if (!d || !n) return DZ_EINVAL;
    float keep[3], sum[3] = { 0 };
    memcpy(keep, d->gyr_bias, sizeof keep);
    memset(d->gyr_bias, 0, sizeof d->gyr_bias);
    for (uint16_t k = 0; k < n; k++) {
        mpu6050_data_t s;
        dz_err_t e = mpu6050_read(d, &s);
        if (e) { memcpy(d->gyr_bias, keep, sizeof keep); return e; }
        for (int i = 0; i < 3; i++) sum[i] += s.gyr[i];
        if (period_ms) pal_delay_ms(period_ms);
    }
    for (int i = 0; i < 3; i++) d->gyr_bias[i] = sum[i] / (float)n;
    return DZ_OK;
}

dz_err_t mpu6050_selftest(void)
{
    mpu6050_t d; memset(&d, 0, sizeof d);
    d.acc_lsb = ACC_LSB[MPU6050_ACC_4G]; d.gyr_lsb = GYR_LSB[MPU6050_GYR_1000];
    /* +1 g 在 z、-500 LSB 在 gx（= -15.24 °/s）、温度原始 0 → 36.53 ℃ */
    const uint8_t raw[14] = { 0, 0, 0, 0, 0x20, 0x00, 0, 0, 0xFE, 0x0C, 0, 0, 0, 0 };
    mpu6050_data_t o; convert(&d, raw, &o);
    if (fabsf(o.acc[2] - G_MPS2) > 1e-3f || fabsf(o.gyr[0] - (-500.0f / 32.8f * DEG2RAD)) > 1e-5f) return DZ_EFAIL;
    if (fabsf(o.temp_c - 36.53f) > 1e-3f || o.acc_sat) return DZ_EFAIL;
    return DZ_OK;
}
