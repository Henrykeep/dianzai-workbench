/* WIT 串口姿态模块驱动，见 wit_imu.h。 */
#include "wit_imu.h"
#include <string.h>

static int16_t s16(const uint8_t *p) { return (int16_t)(uint16_t)(p[0] | ((uint16_t)p[1] << 8)); }

dz_err_t wit_init(wit_t *w, const wit_cfg_t *cfg)
{
    if (!w || !cfg || cfg->model > WIT_HWT101) return DZ_EINVAL;
    memset(w, 0, sizeof *w);
    w->cfg = *cfg;
    if (!w->cfg.gap_ms) w->cfg.gap_ms = 100;
    if (!w->cfg.stale_ms) w->cfg.stale_ms = 100;
    w->ready = true;
    return DZ_OK;
}

static bool decode(wit_t *w, const uint8_t *f, uint32_t now)
{
    uint8_t sum = 0;
    for (int i = 0; i < 10; i++) sum = (uint8_t)(sum + f[i]);
    if (sum != f[10]) { w->bad_sum++; return false; }
    const uint8_t *d = f + 2;
    switch (f[1]) {
    case 0x51: for (int i = 0; i < 3; i++) w->d.acc_g[i] = s16(d + 2 * i) * (16.0f / 32768.0f); break;
    case 0x52: for (int i = 0; i < 3; i++) w->d.gyro_dps[i] = s16(d + 2 * i) * (2000.0f / 32768.0f); break;
    case 0x53:
        w->d.roll = s16(d) * (180.0f / 32768.0f);
        w->d.pitch = s16(d + 2) * (180.0f / 32768.0f);
        w->d.yaw = s16(d + 4) * (180.0f / 32768.0f);
        w->d.t_angle_ms = now; w->d.has_angle = true;
        break;
    case 0x54: for (int i = 0; i < 3; i++) w->d.mag[i] = s16(d + 2 * i); break;
    default: break;   /* 时间/气压/四元数等：校验过但不解析 */
    }
    w->frames++;
    return true;
}

uint16_t wit_feed(wit_t *w, const uint8_t *p, uint16_t n, uint32_t now_ms)
{
    uint16_t got = 0;
    if (!w || !w->ready) return 0;
    for (uint16_t i = 0; i < n; i++) {
        uint8_t b = p[i];
        if (w->n == 0 && b != 0x55) continue;               /* 找帧头 */
        w->buf[w->n++] = b;
        if (w->n < 11) continue;
        if (decode(w, w->buf, now_ms)) { got++; w->n = 0; continue; }
        /* 校验错：从下一个 0x55 重新同步 */
        uint8_t k = 1;
        while (k < 11 && w->buf[k] != 0x55) k++;
        w->n = (uint8_t)(11 - k);
        memmove(w->buf, w->buf + k, w->n);
    }
    return got;
}

static const uint8_t CMD_UNLOCK[5] = { 0xFF, 0xAA, 0x69, 0x88, 0xB5 };
static const uint8_t CMD_SAVE[5] = { 0xFF, 0xAA, 0x00, 0x00, 0x00 };
static const uint8_t CMD_ZJY[5] = { 0xFF, 0xAA, 0x01, 0x04, 0x00 };
static const uint8_t CMD_ZHWT[5] = { 0xFF, 0xAA, 0x76, 0x00, 0x00 };

uint16_t wit_poll(wit_t *w, uint32_t now_ms)
{
    if (!w || !w->ready) return 0;
    uint16_t got = 0;
    uint8_t tmp[32]; uint16_t n = 0;
    while (pal_uart_read(w->cfg.uart, tmp, sizeof tmp, &n) == DZ_OK && n) {
        got = (uint16_t)(got + wit_feed(w, tmp, n, now_ms));
        if (n < sizeof tmp) break;
    }
    if (w->zstep && (int32_t)(now_ms - w->znext) >= 0) {
        const uint8_t *c = w->zstep == 1 ? CMD_UNLOCK : w->zstep == 2 ? (w->cfg.model == WIT_HWT101 ? CMD_ZHWT : CMD_ZJY) : CMD_SAVE;
        if (pal_uart_write(w->cfg.uart, c, 5) == DZ_OK) {
            w->zstep = (uint8_t)(w->zstep == 3 ? 0 : w->zstep + 1);
            w->znext = now_ms + w->cfg.gap_ms;
        }
    }
    return got;
}

const wit_data_t *wit_data(const wit_t *w) { return w ? &w->d : 0; }

bool wit_fresh(const wit_t *w, uint32_t now_ms)
{
    return w && w->d.has_angle && (uint32_t)(now_ms - w->d.t_angle_ms) <= w->cfg.stale_ms;
}

dz_err_t wit_zero_yaw_start(wit_t *w, uint32_t now_ms)
{
    if (!w || !w->ready) return DZ_EINVAL;
    if (w->zstep) return DZ_EBUSY;
    w->zstep = 1; w->znext = now_ms;
    return DZ_OK;
}

bool wit_zero_busy(const wit_t *w) { return w && w->zstep != 0; }

dz_err_t wit_imu_selftest(void)
{
    /* 手册例帧：角度 roll=0x0100 → 1.40625° */
    wit_t w; wit_cfg_t c = { PAL_ID_NONE, WIT_JY61P, 0, 0 };
    if (wit_init(&w, &c) != DZ_OK) return DZ_EIO;
    uint8_t f[11] = { 0x55, 0x53, 0x00, 0x01, 0, 0, 0, 0, 0, 0, 0 };
    for (int i = 0; i < 10; i++) f[10] = (uint8_t)(f[10] + f[i]);
    if (wit_feed(&w, f, 11, 0) != 1) return DZ_EIO;
    float e = w.d.roll - 1.40625f;
    return (e < 1e-4f && e > -1e-4f) ? DZ_OK : DZ_EIO;
}
