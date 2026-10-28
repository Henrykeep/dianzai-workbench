/**
 * @file qd4310.h
 * @brief QD4310 串口无刷电机驱动器协议驱动（按协议文档重写，不含任何厂商例程代码）。
 *
 * 下行 5 字节：[id][cmd][val_lo][val_hi][crc8]；上行 10 字节：[id][status][rsv][cur i16][spd i16][ang u16][crc8]。
 * CRC8：多项式 0x07、初值 0x00、不反射（CRC-8/SMBUS），覆盖除 CRC 外的全部字节。
 * 缩放：电流 ±10 A ↔ ±32767；转速 ±1000 rpm ↔ ±32767；角度 0..360° ↔ 0..65535（u16，避开 int16 溢出）。
 * 发送：只发不等（pal_uart_write 非阻塞，忙则计 tx_busy 并丢弃）；接收：qd4310_poll 从 pal_uart_read
 * 读字节，滑动窗口找“id 匹配 + CRC 正确”的 10 字节帧，坏字节逐个丢弃重同步。
 * 【未验证】协议字段来自用户两份工程的阅读整理（P1/P2），CRC 初值 0x00 是推断，上板前须用实物抓包核对。
 * 版本：QD4310_VERSION
 */
#ifndef QD4310_H
#define QD4310_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "pal.h"
#define QD4310_VERSION "1.0.0"

enum {
    QD_CMD_NOP = 0x00, QD_CMD_ENABLE = 0x01, QD_CMD_DISABLE = 0x02, QD_CMD_CURRENT = 0x03,
    QD_CMD_SPEED = 0x04, QD_CMD_ANGLE = 0x05, QD_CMD_LOW_SPEED = 0x06, QD_CMD_STEP_ANGLE = 0x07,
    QD_CMD_CLEAR_FAULT = 0xFB, QD_CMD_SET_ZERO = 0xFE, QD_CMD_REBOOT = 0xFF
};
#define QD4310_TX_LEN 5u
#define QD4310_RX_LEN 10u

typedef struct {
    uint8_t status;       /**< 原样保留，位含义【未验证】 */
    float current_a, speed_rpm, angle_deg;
    uint32_t t_ms;        /**< 收到时刻 pal_millis() */
} qd4310_fb_t;

typedef struct {
    pal_id_t uart;
    uint8_t id;
    uint8_t rx[QD4310_RX_LEN];
    uint8_t rx_n;
    bool have_fb;
    qd4310_fb_t fb;
    uint32_t rx_ok, rx_err, tx_busy;
} qd4310_t;

uint8_t qd4310_crc8(const uint8_t *p, uint16_t n);
/** 纯编码：把命令写进 out[5]。 */
void qd4310_encode(uint8_t id, uint8_t cmd, uint16_t val, uint8_t out[QD4310_TX_LEN]);
/** 纯解码：10 字节帧 → 反馈；id 或 CRC 不对返回 false。 */
bool qd4310_decode(const uint8_t in[QD4310_RX_LEN], uint8_t id, qd4310_fb_t *fb);

dz_err_t qd4310_init(qd4310_t *m, pal_id_t uart, uint8_t id);
dz_err_t qd4310_cmd(qd4310_t *m, uint8_t cmd, uint16_t val);
dz_err_t qd4310_enable(qd4310_t *m, bool on);
dz_err_t qd4310_set_current(qd4310_t *m, float amps);     /**< 钳到 ±10 A */
dz_err_t qd4310_set_speed(qd4310_t *m, float rpm);        /**< 钳到 ±1000 rpm */
dz_err_t qd4310_set_angle_deg(qd4310_t *m, float deg);    /**< 绝对角，取模到 [0,360) */
/** 处理收到的字节；收到新反馈返回 true。主循环或周期任务调用。 */
bool qd4310_feed(qd4310_t *m, const uint8_t *buf, uint16_t n, uint32_t now_ms);
bool qd4310_poll(qd4310_t *m);
/** 最近一次反馈距今不超过 timeout_ms。 */
bool qd4310_online(const qd4310_t *m, uint32_t now_ms, uint32_t timeout_ms);
dz_err_t qd4310_selftest(void);
#endif
