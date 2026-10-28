#include "bt_serial.h"
#include <string.h>

dz_err_t bt_init(bt_t *b, const bt_cfg_t *c)
{
    if (!b || !c) return DZ_EINVAL;
    b->ready = false;
    if (c->module > BT_JDY31 || c->at_timeout_ms < 100u) return DZ_EINVAL;
    b->cfg = *c; b->len = 0; b->overflow = false; b->n_cmds = 0; b->cur = 0;
    b->at = BT_AT_IDLE; b->deadline = 0; b->lines = 0; b->dropped = 0; b->line[0] = '\0';
    if (c->en != PAL_ID_NONE) { dz_err_t e = pal_gpio_write(c->en, false); if (e != DZ_OK) return e; }
    b->ready = true;
    return DZ_OK;
}

static dz_err_t write_str(bt_t *b, const char *s)
{
    size_t n = strlen(s);
    if (n == 0u || n > 255u) return DZ_EINVAL;
    bool idle = true;
    dz_err_t e = pal_uart_tx_idle(b->cfg.uart, &idle);
    if (e != DZ_OK) return e;
    if (!idle) return DZ_EBUSY;
    return pal_uart_write(b->cfg.uart, (const uint8_t *)s, (uint16_t)n);
}

dz_err_t bt_send_line(bt_t *b, const char *s)
{
    if (!b || !b->ready) return DZ_ESTATE;
    if (!s) return DZ_EINVAL;
    char buf[BT_LINE_MAX + 3u];
    size_t n = strlen(s);
    if (n > BT_LINE_MAX) return DZ_EINVAL;
    memcpy(buf, s, n); buf[n] = '\r'; buf[n + 1u] = '\n'; buf[n + 2u] = '\0';
    return write_str(b, buf);
}

static int baud_code_jdy(uint32_t baud)
{
    switch (baud) { case 9600u: return 4; case 19200u: return 5; case 38400u: return 6; case 57600u: return 7; case 115200u: return 8; default: return -1; }
}

static void u32_to_str(uint32_t v, char *out)
{
    char t[11]; int k = 0;
    do { t[k++] = (char)('0' + v % 10u); v /= 10u; } while (v && k < 10);
    while (k) *out++ = t[--k];
    *out = '\0';
}

static dz_err_t send_cur(bt_t *b, uint32_t now_ms)
{
    char buf[BT_AT_CMD_MAX + 2u];
    size_t n = strlen(b->cmds[b->cur]);
    memcpy(buf, b->cmds[b->cur], n); buf[n] = '\r'; buf[n + 1u] = '\n'; buf[n + 2u] = '\0';
    b->deadline = now_ms + b->cfg.at_timeout_ms;
    return write_str(b, buf);
}

dz_err_t bt_config_start(bt_t *b, const char *name, uint32_t baud, uint32_t now_ms)
{
    if (!b || !b->ready) return DZ_ESTATE;
    if (b->at == BT_AT_BUSY) return DZ_EBUSY;
    if (name) {
        size_t n = strlen(name);
        if (n == 0u || n > 20u) return DZ_EINVAL;
        for (size_t i = 0; i < n; i++) if (name[i] < 0x21 || name[i] > 0x7E || name[i] == ',') return DZ_EINVAL;
    }
    if (baud && baud_code_jdy(baud) < 0) return DZ_EINVAL;
    bool hc = b->cfg.module == BT_HC05;
    b->n_cmds = 0;
    strcpy(b->cmds[b->n_cmds++], "AT");
    if (name) {
        strcpy(b->cmds[b->n_cmds], hc ? "AT+NAME=" : "AT+NAME");
        strcat(b->cmds[b->n_cmds++], name);
    }
    if (baud) {
        char num[12];
        if (hc) { u32_to_str(baud, num); strcpy(b->cmds[b->n_cmds], "AT+UART="); strcat(b->cmds[b->n_cmds], num); strcat(b->cmds[b->n_cmds++], ",0,0"); }
        else { u32_to_str((uint32_t)baud_code_jdy(baud), num); strcpy(b->cmds[b->n_cmds], "AT+BAUD"); strcat(b->cmds[b->n_cmds++], num); }
    }
    b->cur = 0; b->at = BT_AT_BUSY;
    dz_err_t e = send_cur(b, now_ms);
    if (e != DZ_OK) b->at = BT_AT_FAIL;
    return e;
}

static void at_reply(bt_t *b, const char *ln, uint32_t now_ms)
{
    if (strcmp(ln, "OK") == 0 || strncmp(ln, "+OK", 3) == 0 || strncmp(ln, "OK", 2) == 0) {
        if (++b->cur >= b->n_cmds) { b->at = BT_AT_DONE; return; }
        if (send_cur(b, now_ms) != DZ_OK) b->at = BT_AT_FAIL;
    } else if (strncmp(ln, "ERROR", 5) == 0 || strncmp(ln, "+ERR", 4) == 0) {
        b->at = BT_AT_FAIL;
    }
    /* 其它（如 "+NAME:xx" 回显）忽略 */
}

bool bt_poll(bt_t *b, uint32_t now_ms, char *out, uint16_t out_sz)
{
    if (!b || !b->ready) return false;
    if (b->at == BT_AT_BUSY && (int32_t)(now_ms - b->deadline) > 0) b->at = BT_AT_FAIL;
    /* 逐字节取，拿到一行就返回，剩下的字节留在端口缓冲里下次再取（不会丢） */
    for (unsigned guard = 0; guard < 256u; guard++) {
        uint8_t byte = 0; uint16_t got = 0;
        if (pal_uart_read(b->cfg.uart, &byte, 1u, &got) != DZ_OK || got == 0u) return false;
        char ch = (char)byte;
        if (ch == '\r') continue;
        if (ch != '\n') {
            if (b->len < BT_LINE_MAX) b->line[b->len++] = ch; else b->overflow = true;
            continue;
        }
        b->line[b->len] = '\0';
        bool bad = b->overflow; uint16_t len = b->len;
        b->len = 0; b->overflow = false;
        if (bad) { b->dropped++; continue; }
        if (len == 0u) continue;
        if (b->at == BT_AT_BUSY) { at_reply(b, b->line, now_ms); continue; }
        b->lines++;
        if (out && out_sz) {
            uint16_t k = len < out_sz - 1u ? len : (uint16_t)(out_sz - 1u);
            memcpy(out, b->line, k); out[k] = '\0';
        }
        return true;
    }
    return false;
}

bt_at_state_t bt_at_state(const bt_t *b) { return b ? b->at : BT_AT_FAIL; }
const char *bt_at_current(const bt_t *b) { return (b && b->n_cmds && b->cur < b->n_cmds) ? b->cmds[b->cur] : ""; }

bool bt_connected(const bt_t *b, bool *known)
{
    bool on = false;
    bool ok = b && b->ready && b->cfg.state != PAL_ID_NONE && pal_gpio_read(b->cfg.state, &on) == DZ_OK;
    if (known) *known = ok;
    return ok && on;
}

dz_err_t bt_set_en(bt_t *b, bool on)
{
    if (!b || !b->ready) return DZ_ESTATE;
    return b->cfg.en != PAL_ID_NONE ? pal_gpio_write(b->cfg.en, on) : DZ_ENOTSUP;
}

dz_err_t bt_serial_selftest(void)
{
    if (baud_code_jdy(115200u) != 8 || baud_code_jdy(1234u) != -1) return DZ_EFAIL;
    char t[12]; u32_to_str(38400u, t);
    if (strcmp(t, "38400") != 0) return DZ_EFAIL;
    u32_to_str(0u, t);
    if (strcmp(t, "0") != 0) return DZ_EFAIL;
    return DZ_OK;
}
