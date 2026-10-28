#include "qd4310.h"
#include <math.h>
#include <string.h>

uint8_t qd4310_crc8(const uint8_t *p, uint16_t n)
{
    uint8_t c = 0x00u;
    uint16_t i; int b;
    for (i = 0u; i < n; i++) {
        c ^= p[i];
        for (b = 0; b < 8; b++) c = (uint8_t)((c & 0x80u) ? (((unsigned)c << 1) ^ 0x07u) : ((unsigned)c << 1));
    }
    return c;
}

void qd4310_encode(uint8_t id, uint8_t cmd, uint16_t val, uint8_t out[QD4310_TX_LEN])
{
    out[0] = id; out[1] = cmd; out[2] = (uint8_t)(val & 0xFFu); out[3] = (uint8_t)(val >> 8);
    out[4] = qd4310_crc8(out, 4u);
}

static int16_t rd_i16(const uint8_t *p) { return (int16_t)(uint16_t)(p[0] | ((uint16_t)p[1] << 8)); }

bool qd4310_decode(const uint8_t in[QD4310_RX_LEN], uint8_t id, qd4310_fb_t *fb)
{
    if (in[0] != id || qd4310_crc8(in, QD4310_RX_LEN - 1u) != in[QD4310_RX_LEN - 1u]) return false;
    if (fb) {
        fb->status = in[1];
        fb->current_a = (float)rd_i16(&in[3]) * (10.0f / 32767.0f);
        fb->speed_rpm = (float)rd_i16(&in[5]) * (1000.0f / 32767.0f);
        fb->angle_deg = (float)(uint16_t)rd_i16(&in[7]) * (360.0f / 65536.0f);
    }
    return true;
}

dz_err_t qd4310_init(qd4310_t *m, pal_id_t uart, uint8_t id)
{
    if (!m) return DZ_EINVAL;
    memset(m, 0, sizeof *m);
    m->uart = uart; m->id = id;
    return DZ_OK;
}

dz_err_t qd4310_cmd(qd4310_t *m, uint8_t cmd, uint16_t val)
{
    uint8_t f[QD4310_TX_LEN];
    dz_err_t e;
    if (!m) return DZ_EINVAL;
    qd4310_encode(m->id, cmd, val, f);
    e = pal_uart_write(m->uart, f, QD4310_TX_LEN);
    if (e == DZ_EBUSY) m->tx_busy++;
    return e;
}

static uint16_t scale_i16(float v, float full)
{
    float s;
    if (!(v == v)) v = 0.0f;                       /* NaN → 0 */
    if (v > full) v = full;
    if (v < -full) v = -full;
    s = v * (32767.0f / full);
    return (uint16_t)(int16_t)lrintf(s);
}

dz_err_t qd4310_enable(qd4310_t *m, bool on) { return qd4310_cmd(m, on ? QD_CMD_ENABLE : QD_CMD_DISABLE, 0u); }
dz_err_t qd4310_set_current(qd4310_t *m, float a) { return qd4310_cmd(m, QD_CMD_CURRENT, scale_i16(a, 10.0f)); }
dz_err_t qd4310_set_speed(qd4310_t *m, float rpm) { return qd4310_cmd(m, QD_CMD_SPEED, scale_i16(rpm, 1000.0f)); }

dz_err_t qd4310_set_angle_deg(qd4310_t *m, float deg)
{
    float d;
    long c;
    if (!(deg == deg) || isinf(deg)) return DZ_EINVAL;
    d = fmodf(deg, 360.0f);
    if (d < 0.0f) d += 360.0f;
    c = lrintf(d * (65536.0f / 360.0f));
    return qd4310_cmd(m, QD_CMD_ANGLE, (uint16_t)(c & 0xFFFF));   /* 360° 回绕到 0 */
}

bool qd4310_feed(qd4310_t *m, const uint8_t *buf, uint16_t n, uint32_t now)
{
    bool got = false;
    uint16_t i;
    if (!m || !buf) return false;
    for (i = 0u; i < n; i++) {
        m->rx[m->rx_n++] = buf[i];
        if (m->rx_n == 1u && m->rx[0] != m->id) { m->rx_n = 0u; continue; }
        if (m->rx_n < QD4310_RX_LEN) continue;
        if (qd4310_decode(m->rx, m->id, &m->fb)) {
            m->fb.t_ms = now; m->have_fb = true; m->rx_ok++; m->rx_n = 0u; got = true;
        } else {                                        /* 滑窗：丢一个字节，重找帧头 */
            uint8_t k, j = 0u;
            m->rx_err++;
            for (k = 1u; k < QD4310_RX_LEN; k++) if (m->rx[k] == m->id) { j = k; break; }
            if (j == 0u) { m->rx_n = 0u; continue; }
            memmove(m->rx, &m->rx[j], (size_t)(QD4310_RX_LEN - j));
            m->rx_n = (uint8_t)(QD4310_RX_LEN - j);
        }
    }
    return got;
}

bool qd4310_poll(qd4310_t *m)
{
    uint8_t b[32];
    uint16_t got = 0u;
    bool any = false;
    if (!m) return false;
    while (pal_uart_read(m->uart, b, (uint16_t)sizeof b, &got) == DZ_OK && got) {
        any |= qd4310_feed(m, b, got, pal_millis());
        if (got < sizeof b) break;
    }
    return any;
}

bool qd4310_online(const qd4310_t *m, uint32_t now, uint32_t timeout_ms)
{
    return m && m->have_fb && (uint32_t)(now - m->fb.t_ms) <= timeout_ms;
}

dz_err_t qd4310_selftest(void)
{
    static const uint8_t chk[9] = { '1', '2', '3', '4', '5', '6', '7', '8', '9' };
    uint8_t f[QD4310_TX_LEN], r[QD4310_RX_LEN + 3];
    qd4310_t m;
    if (qd4310_crc8(chk, 9u) != 0xF4u) return DZ_EFAIL;       /* CRC-8/SMBUS 标准校验值 */
    qd4310_encode(0u, QD_CMD_ANGLE, 0x4000u, f);
    if (f[2] != 0x00u || f[3] != 0x40u) return DZ_EFAIL;
    (void)qd4310_init(&m, PAL_ID_NONE, 0u);
    r[0] = 0x55u; r[1] = 0x00u;                                 /* 垃圾 + 一个假帧头，真帧在 r[2..11] */
    r[2] = 0u; r[3] = 0x10u; r[4] = 0u; r[5] = 0xFFu; r[6] = 0x7Fu; r[7] = 0u; r[8] = 0u;
    r[9] = 0x00u; r[10] = 0x80u; r[11] = qd4310_crc8(&r[2], 9u);
    if (!qd4310_feed(&m, r, 12u, 7u)) return DZ_EFAIL;
    return (m.fb.status == 0x10u && m.fb.current_a > 9.99f && m.fb.angle_deg > 179.9f && m.fb.angle_deg < 180.1f)
        ? DZ_OK : DZ_EFAIL;
}
