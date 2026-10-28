/* IMU 驱动测试：在 host-sim 的 I2C/SPI 上挂假 MPU6050 / 假 BMI088 */
#include <string.h>
#include "tt.h"
#include "board_gen.h"
#include "host_sim.h"
#include "mpu6050.h"
#include "bmi088.h"
#include "attitude.h"
#include "dzimu.h"

/* ---------- 假 MPU6050：128 个寄存器，0x3B 起放数据 ---------- */
typedef struct { uint8_t addr; uint8_t reg[128]; bool stuck_cfg; int reads; } fake_mpu_t;
static dz_err_t mpu_cb(void *ctx, uint8_t addr7, uint8_t reg, uint8_t *buf, uint16_t n, bool write)
{
    fake_mpu_t *m = ctx;
    if (addr7 != m->addr) return DZ_EIO;
    for (uint16_t i = 0; i < n; i++) {
        uint8_t r = (uint8_t)(reg + i) & 0x7Fu;
        if (write) { if (!(m->stuck_cfg && r == 0x1Bu)) m->reg[r] = buf[i]; if (r == 0x6Bu && (buf[i] & 0x80u)) m->reg[r] = 0x40u; }
        else buf[i] = m->reg[r];
    }
    if (!write) m->reads++;
    return DZ_OK;
}
static void mpu_set(fake_mpu_t *m, const int16_t a[3], int16_t t, const int16_t g[3])
{
    int16_t v[7] = { a[0], a[1], a[2], t, g[0], g[1], g[2] };
    for (int i = 0; i < 7; i++) { m->reg[0x3B + 2 * i] = (uint8_t)((uint16_t)v[i] >> 8); m->reg[0x3C + 2 * i] = (uint8_t)v[i]; }
}

TEST(mpu6050_ok)
{
    fake_mpu_t m; memset(&m, 0, sizeof m); m.addr = 0x68; m.reg[0x75] = 0x68;
    host_sim_i2c_attach(RES_I2C_IMU, mpu_cb, &m);
    mpu6050_t d; mpu6050_cfg_t c = mpu6050_cfg_default(RES_I2C_IMU);
    CHECK(mpu6050_init(&d, &c) == DZ_OK);
    CHECK(m.reg[0x6B] == 0x01 && m.reg[0x1B] == (2 << 3) && m.reg[0x1C] == (1 << 3) && m.reg[0x1A] == 3);
    const int16_t a[3] = { 0, -8192, 0 }, g[3] = { 328, 0, -328 };
    mpu_set(&m, a, 340, g);
    mpu6050_data_t o;
    CHECK(mpu6050_read(&d, &o) == DZ_OK);
    CHECK_NEAR(o.acc[1], -9.80665, 1e-3);
    CHECK_NEAR(o.gyr[0], 10.0 * 0.0174533, 1e-4);
    CHECK_NEAR(o.gyr[2], -10.0 * 0.0174533, 1e-4);
    CHECK_NEAR(o.temp_c, 37.53, 1e-3);
    CHECK(mpu6050_calib_gyro(&d, 10, 0) == DZ_OK);
    CHECK(mpu6050_read(&d, &o) == DZ_OK);
    CHECK_NEAR(o.gyr[0], 0.0, 1e-5);
    host_sim_fail_next(HS_FAIL_I2C, 1);
    float bias0 = d.gyr_bias[0];
    CHECK(mpu6050_calib_gyro(&d, 5, 0) == DZ_ETIMEOUT);
    CHECK(d.gyr_bias[0] == bias0);           /* 标定失败不改零偏 */
    CHECK(d.errors == 1);
    host_sim_i2c_attach(RES_I2C_IMU, NULL, NULL);
}

TEST(mpu6050_errors)
{
    fake_mpu_t m; memset(&m, 0, sizeof m); m.addr = 0x69; m.reg[0x75] = 0x68;
    host_sim_i2c_attach(RES_I2C_IMU, mpu_cb, &m);
    mpu6050_t d; mpu6050_cfg_t c = mpu6050_cfg_default(RES_I2C_IMU);
    CHECK(mpu6050_init(&d, &c) == DZ_EIO);          /* 地址不对：无应答 */
    mpu6050_data_t o;
    CHECK(mpu6050_read(&d, &o) == DZ_ESTATE);
    c.addr = 0x69; m.reg[0x75] = 0x12;
    CHECK(mpu6050_init(&d, &c) == DZ_ENODEV);       /* 不是 MPU */
    m.reg[0x75] = 0x68; m.stuck_cfg = true;
    CHECK(mpu6050_init(&d, &c) == DZ_EIO);          /* 读回不一致 */
    c.acc_fs = 7;
    CHECK(mpu6050_init(&d, &c) == DZ_EINVAL);
    host_sim_i2c_attach(RES_I2C_IMU, NULL, NULL);
}

/* ---------- 假 BMI088：加速度计要哑读切 SPI + 哑字节；陀螺 BW 读回 bit7=1 ---------- */
typedef struct { uint8_t reg[128]; bool spi_mode; bool is_acc; int resets; } fake_bmi_t;
static dz_err_t bmi_cb(void *ctx, const uint8_t *tx, uint8_t *rx, uint16_t n)
{
    fake_bmi_t *b = ctx;
    uint8_t r = tx[0] & 0x7Fu;
    memset(rx, 0, n);
    if (b->is_acc && !b->spi_mode) { b->spi_mode = true; memset(rx, 0xFF, n); return DZ_OK; }  /* 第一次只切模式 */
    if (tx[0] & 0x80u) {
        uint16_t off = b->is_acc ? 2u : 1u;
        for (uint16_t i = off; i < n; i++) {
            uint8_t v = b->reg[(r + i - off) & 0x7Fu];
            if (!b->is_acc && r == 0x10u && i == off) v |= 0x80u;
            rx[i] = v;
        }
    } else {
        for (uint16_t i = 1; i < n; i++) b->reg[(r + i - 1) & 0x7Fu] = tx[i];
        if ((b->is_acc && r == 0x7Eu) || (!b->is_acc && r == 0x14u)) { b->resets++; if (b->is_acc) b->spi_mode = false; }
    }
    return DZ_OK;
}

TEST(bmi088_ok)
{
    fake_bmi_t A, G; memset(&A, 0, sizeof A); memset(&G, 0, sizeof G);
    A.is_acc = true; A.reg[0] = 0x1E; G.reg[0] = 0x0F;
    host_sim_spi_attach(RES_SPI_IMU_ACC, bmi_cb, &A);
    host_sim_spi_attach(RES_SPI_IMU_GYR, bmi_cb, &G);
    bmi088_t d; bmi088_cfg_t c = bmi088_cfg_default(RES_SPI_IMU_ACC, RES_SPI_IMU_GYR);
    CHECK(bmi088_init(&d, &c) == DZ_OK);
    CHECK(A.resets == 1 && G.resets == 1);
    CHECK(A.reg[0x7D] == 4 && A.reg[0x7C] == 0 && A.reg[0x41] == 1 && A.reg[0x40] == 0xAB);
    CHECK(G.reg[0x0F] == 1 && G.reg[0x10] == 2);
    /* 1 g 在 z（±6 g：5461 LSB）；gy = 3277 LSB ≈ 100 °/s */
    A.reg[0x16] = 0x55; A.reg[0x17] = 0x15;
    G.reg[0x04] = 0xCD; G.reg[0x05] = 0x0C;
    bmi088_data_t o;
    CHECK(bmi088_read(&d, &o) == DZ_OK);
    CHECK_NEAR(o.acc[2], 9.80665, 0.01);
    CHECK_NEAR(o.gyr[1], 1.74533, 0.001);
    CHECK_NEAR(o.acc[0], 0.0, 1e-6);
    A.reg[0x22] = 0x10; A.reg[0x23] = 0x00;      /* 0x10<<3 = 128 → 23 + 16 = 39 ℃ */
    float t; CHECK(bmi088_read_temp(&d, &t) == DZ_OK); CHECK_NEAR(t, 39.0, 1e-4);
    A.reg[0x22] = 0xFF; A.reg[0x23] = 0xE0;      /* -1 → 22.875 ℃ */
    CHECK(bmi088_read_temp(&d, &t) == DZ_OK); CHECK_NEAR(t, 22.875, 1e-4);
    host_sim_spi_attach(RES_SPI_IMU_ACC, NULL, NULL);
    host_sim_spi_attach(RES_SPI_IMU_GYR, NULL, NULL);
}

TEST(bmi088_errors)
{
    bmi088_t d; bmi088_cfg_t c = bmi088_cfg_default(RES_SPI_IMU_ACC, RES_SPI_IMU_GYR);
    CHECK(bmi088_init(&d, &c) == DZ_ENODEV);       /* 没挂芯片：MISO 0xFF */
    fake_bmi_t A, G; memset(&A, 0, sizeof A); memset(&G, 0, sizeof G);
    A.is_acc = true; A.reg[0] = 0x1E; G.reg[0] = 0x0F;
    /* 片选接反：acc id 上挂的是陀螺 */
    host_sim_spi_attach(RES_SPI_IMU_ACC, bmi_cb, &G);
    host_sim_spi_attach(RES_SPI_IMU_GYR, bmi_cb, &A);
    CHECK(bmi088_init(&d, &c) == DZ_ENODEV);
    host_sim_spi_attach(RES_SPI_IMU_ACC, NULL, NULL);
    host_sim_spi_attach(RES_SPI_IMU_GYR, NULL, NULL);
}

TEST(attitude_and_dzimu)
{
    CHECK(mpu6050_selftest() == DZ_OK);
    CHECK(bmi088_selftest() == DZ_OK);
    CHECK(attitude_selftest() == DZ_OK);
    attitude_t a; CHECK(attitude_init(&a, 0.5f, 0.15f) == DZ_OK);
    const float g0[3] = { 0, 0, 0 };
    const float shake[3] = { 15.0f, 0, 9.8f };
    CHECK(attitude_update(&a, shake, g0, 0.005f) == DZ_ESTATE);   /* 第一拍在晃：不定初值 */
    /* 俯仰 20°：acc = (-g sin20, 0, g cos20) */
    const float acc[3] = { -9.80665f * 0.3420201f, 0, 9.80665f * 0.9396926f };
    for (int i = 0; i < 200; i++) CHECK(attitude_update(&a, acc, g0, 0.005f) == DZ_OK);
    CHECK_NEAR(a.pitch, 0.3490659, 1e-3);
    /* 急加速：只积分陀螺，角度不被拉偏 */
    for (int i = 0; i < 50; i++) attitude_update(&a, shake, g0, 0.005f);
    CHECK_NEAR(a.pitch, 0.3490659, 1e-3);
    CHECK(attitude_update(&a, acc, g0, 0.0f) == DZ_EINVAL);
    CHECK(dzimu_selftest() == DZ_OK);
}

void suite_imu(void)
{
    RUN(mpu6050_ok); RUN(mpu6050_errors); RUN(bmi088_ok); RUN(bmi088_errors); RUN(attitude_and_dzimu);
}
