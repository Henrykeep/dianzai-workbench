#include <math.h>
#include <string.h>
#include "bmi088.h"

#define A_CHIP_ID 0x00u
#define A_DATA    0x12u
#define A_TEMP    0x22u
#define A_CONF    0x40u
#define A_RANGE   0x41u
#define A_PWR_CONF 0x7Cu
#define A_PWR_CTRL 0x7Du
#define A_SOFTRESET 0x7Eu
#define G_CHIP_ID 0x00u
#define G_DATA    0x02u
#define G_RANGE   0x0Fu
#define G_BW      0x10u
#define G_LPM1    0x11u
#define G_SOFTRESET 0x14u
#define G_MPS2  9.80665f
#define DEG2RAD 0.017453292519943295f

static const float GYR_DPS[5] = { 2000.0f, 1000.0f, 500.0f, 250.0f, 125.0f };

bmi088_cfg_t bmi088_cfg_default(pal_id_t spi_acc, pal_id_t spi_gyr)
{
    return (bmi088_cfg_t){ spi_acc, spi_gyr, BMI088_ACC_6G, BMI088_GYR_1000, 0xABu, 0x02u };
}

/* 加速度计 SPI 读：发 reg|0x80，回来的第 1 字节是哑字节，第 2 字节起才是数据（手册 §6.1.2） */
static dz_err_t acc_rd(bmi088_t *d, uint8_t reg, uint8_t *buf, uint16_t n)
{
    uint8_t tx[24] = { 0 }, rx[24];
    if (n + 2u > sizeof tx) return DZ_EINVAL;
    tx[0] = (uint8_t)(reg | 0x80u);
    dz_err_t e = pal_spi_xfer(d->cfg.spi_acc, tx, rx, (uint16_t)(n + 2u));
    if (!e) memcpy(buf, rx + 2, n);
    return e;
}
static dz_err_t gyr_rd(bmi088_t *d, uint8_t reg, uint8_t *buf, uint16_t n)
{
    uint8_t tx[24] = { 0 }, rx[24];
    if (n + 1u > sizeof tx) return DZ_EINVAL;
    tx[0] = (uint8_t)(reg | 0x80u);
    dz_err_t e = pal_spi_xfer(d->cfg.spi_gyr, tx, rx, (uint16_t)(n + 1u));
    if (!e) memcpy(buf, rx + 1, n);
    return e;
}
static dz_err_t wr(pal_id_t id, uint8_t reg, uint8_t v)
{
    uint8_t tx[2] = { (uint8_t)(reg & 0x7Fu), v };
    return pal_spi_xfer(id, tx, NULL, 2u);
}

static void scales(bmi088_t *d)
{
    /* 加速度：mg = raw / 32768 × 1000 × 2^(range+1) × 1.5（手册 §5.3.4） */
    d->acc_scale = (float)(1u << (d->cfg.acc_range + 1u)) * 1.5f / 32768.0f * G_MPS2;
    d->gyr_scale = GYR_DPS[d->cfg.gyr_range] / 32768.0f * DEG2RAD;
}

dz_err_t bmi088_init(bmi088_t *d, const bmi088_cfg_t *cfg)
{
    if (!d || !cfg || cfg->acc_range > BMI088_ACC_24G || cfg->gyr_range > BMI088_GYR_125) return DZ_EINVAL;
    memset(d, 0, sizeof *d);
    d->cfg = *cfg;
    scales(d);
    uint8_t id = 0;
    dz_err_t e;
    /* 加速度计：先哑读一次切到 SPI 模式，再读 ID */
    if ((e = acc_rd(d, A_CHIP_ID, &id, 1u))) return e;
    if ((e = acc_rd(d, A_CHIP_ID, &id, 1u))) return e;
    if (id != 0x1Eu) return DZ_ENODEV;
    if ((e = wr(cfg->spi_acc, A_SOFTRESET, 0xB6u))) return e;
    pal_delay_ms(2u);
    if ((e = acc_rd(d, A_CHIP_ID, &id, 1u))) return e;        /* 软复位后又回到 I2C 模式，再哑读一次 */
    if ((e = wr(cfg->spi_acc, A_PWR_CONF, 0x00u))) return e;
    pal_delay_ms(1u);
    if ((e = wr(cfg->spi_acc, A_PWR_CTRL, 0x04u))) return e;
    pal_delay_ms(5u);
    const uint8_t aregs[2] = { A_CONF, A_RANGE }, avals[2] = { cfg->acc_conf, (uint8_t)cfg->acc_range };
    for (int i = 0; i < 2; i++) {
        uint8_t rb = 0xFFu;
        if ((e = wr(cfg->spi_acc, aregs[i], avals[i]))) return e;
        pal_delay_ms(1u);
        if ((e = acc_rd(d, aregs[i], &rb, 1u))) return e;
        if (rb != avals[i]) return DZ_EIO;
    }
    /* 陀螺仪 */
    if ((e = gyr_rd(d, G_CHIP_ID, &id, 1u))) return e;
    if (id != 0x0Fu) return DZ_ENODEV;
    if ((e = wr(cfg->spi_gyr, G_SOFTRESET, 0xB6u))) return e;
    pal_delay_ms(30u);
    const uint8_t gregs[3] = { G_RANGE, G_BW, G_LPM1 }, gvals[3] = { (uint8_t)cfg->gyr_range, cfg->gyr_bw, 0x00u };
    for (int i = 0; i < 3; i++) {
        uint8_t rb = 0xFFu;
        if ((e = wr(cfg->spi_gyr, gregs[i], gvals[i]))) return e;
        pal_delay_ms(1u);
        if ((e = gyr_rd(d, gregs[i], &rb, 1u))) return e;
        if (gregs[i] == G_BW) rb &= 0x7Fu;                       /* BANDWIDTH 读回时 bit7 恒为 1（手册 §5.5.6） */
        if (rb != gvals[i]) return DZ_EIO;
    }
    d->ok = true;
    return DZ_OK;
}

static int16_t le16(const uint8_t *p) { return (int16_t)(uint16_t)((uint16_t)p[1] << 8 | p[0]); }

static void convert(const bmi088_t *d, const uint8_t a[6], const uint8_t g[6], bmi088_data_t *o)
{
    o->acc_sat = false;
    for (int i = 0; i < 3; i++) {
        int16_t ra = le16(a + 2 * i);
        if (ra == INT16_MAX || ra == INT16_MIN) o->acc_sat = true;
        o->acc[i] = (float)ra * d->acc_scale;
        o->gyr[i] = (float)le16(g + 2 * i) * d->gyr_scale - d->gyr_bias[i];
    }
}

dz_err_t bmi088_read(bmi088_t *d, bmi088_data_t *out)
{
    uint8_t a[6], g[6];
    if (!d || !out) return DZ_EINVAL;
    if (!d->ok) return DZ_ESTATE;
    dz_err_t e = acc_rd(d, A_DATA, a, 6u);
    if (!e) e = gyr_rd(d, G_DATA, g, 6u);
    if (e) { d->errors++; return e; }
    convert(d, a, g, out);
    out->temp_c = NAN;
    return DZ_OK;
}

dz_err_t bmi088_read_temp(bmi088_t *d, float *temp_c)
{
    uint8_t t[2];
    if (!d || !temp_c) return DZ_EINVAL;
    dz_err_t e = acc_rd(d, A_TEMP, t, 2u);
    if (e) return e;
    int32_t raw = (int32_t)((uint32_t)t[0] << 3 | (t[1] >> 5));
    if (raw > 1023) raw -= 2048;
    *temp_c = (float)raw * 0.125f + 23.0f;
    return DZ_OK;
}

dz_err_t bmi088_calib_gyro(bmi088_t *d, uint16_t n, uint32_t period_ms)
{
    if (!d || !n) return DZ_EINVAL;
    float keep[3], sum[3] = { 0 };
    memcpy(keep, d->gyr_bias, sizeof keep);
    memset(d->gyr_bias, 0, sizeof d->gyr_bias);
    for (uint16_t k = 0; k < n; k++) {
        bmi088_data_t s;
        dz_err_t e = bmi088_read(d, &s);
        if (e) { memcpy(d->gyr_bias, keep, sizeof keep); return e; }
        for (int i = 0; i < 3; i++) sum[i] += s.gyr[i];
        if (period_ms) pal_delay_ms(period_ms);
    }
    for (int i = 0; i < 3; i++) d->gyr_bias[i] = sum[i] / (float)n;
    return DZ_OK;
}

dz_err_t bmi088_selftest(void)
{
    bmi088_t d; memset(&d, 0, sizeof d);
    d.cfg.acc_range = BMI088_ACC_6G; d.cfg.gyr_range = BMI088_GYR_1000;
    scales(&d);
    /* ±6 g：1 g = 32768/(4×1.5) = 5461 LSB；1000 °/s：32.768 LSB/(°/s) → 3277 LSB ≈ 100 °/s */
    const uint8_t a[6] = { 0, 0, 0, 0, 0x55, 0x15 }, g[6] = { 0xCD, 0x0C, 0, 0, 0, 0 };
    bmi088_data_t o; convert(&d, a, g, &o);
    if (fabsf(o.acc[2] - G_MPS2) > 0.01f || fabsf(o.gyr[0] - 100.0f * DEG2RAD) > 0.001f) return DZ_EFAIL;
    return DZ_OK;
}
