/**
 * @file bt_serial.h
 * @brief HC-05 / HC-06 / JDY-31 类串口蓝牙：按行收发 + 非阻塞 AT 配置（改名、改波特率）+ 连接状态脚。
 *
 * 透传模式下蓝牙就是一根串口线：bt_poll() 把 UART 字节拼成行（\n 结尾，去掉 \r）。
 * AT 配置（bt_config_start）是一个小状态机：依次发 "AT"、改名、改波特率，每条等 OK（≤ at_timeout_ms），
 * 任何一步 ERROR/超时就停在 BT_AT_FAIL。
 *   - HC-05：EN(KEY) 拉高再上电进 AT 模式，AT 波特率固定 38400；命令 AT+NAME=<x>、AT+UART=<baud>,0,0，回 "OK"。
 *   - JDY-31 / HC-06：未连接时即是 AT 模式，波特率 = 当前透传波特率；命令 AT+NAME<x>、AT+BAUD<n>（4=9600 … 8=115200），回 "+OK"/"OK"。
 * board.yaml 的 uart 波特率要和模块当前波特率一致（PAL 不提供运行时改波特率）。
 * 版本：BT_SERIAL_VERSION
 */
#ifndef BT_SERIAL_H
#define BT_SERIAL_H
#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "pal.h"
#define BT_SERIAL_VERSION "1.0.0"
#define BT_LINE_MAX 64u
#define BT_AT_CMD_MAX 40u

typedef enum { BT_HC05 = 0, BT_JDY31 = 1 } bt_module_t;
typedef enum { BT_AT_IDLE = 0, BT_AT_BUSY, BT_AT_DONE, BT_AT_FAIL } bt_at_state_t;

typedef struct {
    pal_id_t uart;
    pal_id_t state;          /**< gpio 输入，连上为有效；PAL_ID_NONE = 不接 */
    pal_id_t en;             /**< gpio 输出（HC-05 KEY/EN）；PAL_ID_NONE = 不接 */
    bt_module_t module;
    uint16_t at_timeout_ms;  /**< 典型 1000 */
} bt_cfg_t;

typedef struct {
    bt_cfg_t cfg;
    char line[BT_LINE_MAX + 1u];
    uint16_t len;
    bool overflow;
    char cmds[3][BT_AT_CMD_MAX];
    uint8_t n_cmds, cur;
    bt_at_state_t at;
    uint32_t deadline;
    uint32_t lines, dropped;
    bool ready;
} bt_t;

dz_err_t bt_init(bt_t *b, const bt_cfg_t *cfg);
/** 收字节拼行。拿到一行完整数据（不含 AT 应答）时拷到 out（≤ out_sz-1 字节 + '\0'）并返回 true。 */
bool bt_poll(bt_t *b, uint32_t now_ms, char *out, uint16_t out_sz);
/** 发一行（自动补 "\r\n"）。UART 忙返回 DZ_EBUSY。 */
dz_err_t bt_send_line(bt_t *b, const char *s);
/** 开始 AT 配置：name 为 NULL 不改名；baud 为 0 不改波特率（仅 9600/19200/38400/57600/115200）。 */
dz_err_t bt_config_start(bt_t *b, const char *name, uint32_t baud, uint32_t now_ms);
bt_at_state_t bt_at_state(const bt_t *b);
/** 当前卡在第几条命令（失败时诊断用）。 */
const char *bt_at_current(const bt_t *b);
/** STATE 脚：已连接。没接 STATE 脚返回 false 并置 *known=false。 */
bool bt_connected(const bt_t *b, bool *known);
/** HC-05：EN 脚（上电前拉高进 AT 模式）。 */
dz_err_t bt_set_en(bt_t *b, bool on);
dz_err_t bt_serial_selftest(void);
#endif
