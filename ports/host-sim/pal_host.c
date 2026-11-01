/**
 * @file pal_host.c
 * @brief pal.h 的 PC 仿真实现。资源数量来自生成的 board_gen.h（boards/host-sim/board.yaml）。
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "board_gen.h"
#include "host_sim.h"

#define MAX_MOTORS 4
#define UART_BUF   4096

extern const char *const g_board_name;
extern const pal_adc_info_t g_host_adc_info[];  /* board_gen.c，按 board.yaml bits/vref/scale */
extern const uint32_t g_host_pwm_freq[];  /* board_gen.c，按 board.yaml freq_hz */

static struct {
    bool inited;
    uint64_t now_us;
    pal_reset_cause_t reset;
    uint32_t wdg_ms; uint64_t wdg_kick_us; bool wdg_bit;
    bool gpio[BOARD_GPIO_COUNT + 1];
    uint16_t pwm[BOARD_PWM_COUNT + 1];
    int32_t enc[BOARD_ENCODER_COUNT + 1];
    float enc_frac[BOARD_ENCODER_COUNT + 1];
    uint16_t adc[BOARD_ADC_COUNT + 1];
    struct { pal_gpio_irq_cb_t cb; void *ctx; uint8_t edge; } girq[BOARD_GPIO_COUNT + 1];
    struct { uint8_t tx[UART_BUF]; uint16_t tx_n; uint8_t rx[UART_BUF]; uint16_t rx_n; bool busy; } uart[BOARD_UART_COUNT + 1];
    struct { pal_timer_cb_t cb; void *ctx; uint32_t period_us; uint64_t next_us; } tmr[BOARD_TIMER_COUNT + 1];
    host_sim_motor_t motor[MAX_MOTORS];
    float speed[MAX_MOTORS];
    int motors;
    host_sim_ev_t ev[256];
    unsigned ev_n;
    unsigned fail[HS_FAIL_COUNT];
    struct { void (*fn)(void *); void *ctx; uint32_t period_us; uint64_t next_us; } per[4];
    struct { host_sim_i2c_fn fn; void *ctx; } i2c[BOARD_I2C_COUNT + 1];
    struct { host_sim_spi_fn fn; void *ctx; } spi[BOARD_SPI_COUNT + 1];
} S;

static bool take_fail(host_sim_fail_t w) { if (S.fail[w]) { S.fail[w]--; return true; } return false; }
static void log_ev(host_sim_ev_type_t t, pal_id_t id, uint32_t v)
{
    if (S.ev_n < sizeof S.ev / sizeof S.ev[0]) S.ev[S.ev_n++] = (host_sim_ev_t){ t, id, v };
}

/* ---------------------------------------------------------------- 仿真控制 */
static host_sim_gpio_read_cb_t g_rd_cb; static void *g_rd_ctx;
void host_sim_reset(void) { memset(&S, 0, sizeof S); g_rd_cb = NULL; g_rd_ctx = NULL; }
uint64_t host_sim_now_us(void) { return S.now_us; }

static void step(void)
{
    const float dt = HOST_SIM_STEP_US * 1e-6f;
    for (int m = 0; m < S.motors; m++) {
        const host_sim_motor_t *p = &S.motor[m];
        float duty = (float)S.pwm[p->pwm] / (float)PAL_DUTY_MAX;
        float u = 0.0f;
        bool a = S.gpio[p->in1];
        if (p->dir_mode) u = a ? duty : -duty;
        else {
            bool b = S.gpio[p->in2];
            if (a && !b) u = duty; else if (!a && b) u = -duty; else u = 0.0f;
        }
        float w = S.speed[m];
        float target = p->gain_rps * u;
        /* 负载总是阻碍运动方向 */
        if (w > 0) target -= p->load_rps; else if (w < 0) target += p->load_rps;
        w += (target - w) * dt / p->tau_s;
        S.speed[m] = w;
        float c = w * p->counts_per_rev * dt + S.enc_frac[p->enc];
        int32_t whole = (int32_t)c;
        S.enc_frac[p->enc] = c - (float)whole;
        S.enc[p->enc] += whole;
    }
    S.now_us += HOST_SIM_STEP_US;
    for (unsigned i = 0; i < 4; i++)
        if (S.per[i].fn && S.now_us >= S.per[i].next_us) { S.per[i].next_us += S.per[i].period_us; S.per[i].fn(S.per[i].ctx); }
    for (unsigned i = 0; i < BOARD_TIMER_COUNT; i++) {
        if (S.tmr[i].cb && S.now_us >= S.tmr[i].next_us) {
            S.tmr[i].next_us += S.tmr[i].period_us;
            S.tmr[i].cb(S.tmr[i].ctx);
        }
    }
}

void host_sim_run_us(uint64_t us)
{
    for (uint64_t t = 0; t < us; t += HOST_SIM_STEP_US) step();
}

int host_sim_bind_motor(const host_sim_motor_t *m)
{
    if (!m || S.motors >= MAX_MOTORS || m->tau_s <= 0 || m->pwm >= BOARD_PWM_COUNT ||
        m->in1 >= BOARD_GPIO_COUNT || m->enc >= BOARD_ENCODER_COUNT ||
        (!m->dir_mode && m->in2 >= BOARD_GPIO_COUNT)) return -1;
    S.motor[S.motors] = *m;
    S.speed[S.motors] = 0;
    return S.motors++;
}
float host_sim_motor_speed_rps(int m) { return (m >= 0 && m < S.motors) ? S.speed[m] : 0.0f; }
void  host_sim_motor_set_load(int m, float l) { if (m >= 0 && m < S.motors) S.motor[m].load_rps = l; }

bool host_sim_gpio_level(pal_id_t id) { return id < BOARD_GPIO_COUNT ? S.gpio[id] : false; }
/* 外部驱动输入脚；电平变化且挂了匹配边沿的中断回调时，同步调用它（模拟 EXTI，t_us = 当前仿真时间） */
void host_sim_gpio_set_input(pal_id_t id, bool a)
{
    if (id >= BOARD_GPIO_COUNT) return;
    bool old = S.gpio[id];
    S.gpio[id] = a;
    if (old == a || !S.girq[id].cb) return;
    if (S.girq[id].edge & (a ? PAL_EDGE_RISING : PAL_EDGE_FALLING)) S.girq[id].cb(S.girq[id].ctx, a, (uint32_t)S.now_us);
}
dz_err_t pal_gpio_irq_attach(pal_id_t id, pal_edge_t edge, pal_gpio_irq_cb_t cb, void *ctx)
{
    if (id >= BOARD_GPIO_COUNT) return DZ_ENODEV;
    if (!cb || edge < PAL_EDGE_RISING || edge > PAL_EDGE_BOTH) return DZ_EINVAL;
    S.girq[id].cb = cb; S.girq[id].ctx = ctx; S.girq[id].edge = (uint8_t)edge;
    return DZ_OK;
}
dz_err_t pal_gpio_irq_detach(pal_id_t id)
{
    if (id >= BOARD_GPIO_COUNT) return DZ_ENODEV;
    S.girq[id].cb = 0;
    return DZ_OK;
}
uint16_t host_sim_pwm_duty(pal_id_t id) { return id < BOARD_PWM_COUNT ? S.pwm[id] : 0; }
void host_sim_enc_add(pal_id_t id, int32_t c) { if (id < BOARD_ENCODER_COUNT) S.enc[id] = (int32_t)((uint32_t)S.enc[id] + (uint32_t)c); }
void host_sim_adc_set(pal_id_t id, uint16_t r) { if (id < BOARD_ADC_COUNT) S.adc[id] = r; }
void host_sim_uart_set_busy(pal_id_t id, bool b) { if (id < BOARD_UART_COUNT) S.uart[id].busy = b; }
int host_sim_add_periodic(uint32_t period_us, void (*fn)(void *), void *ctx)
{
    if (!fn || period_us < HOST_SIM_STEP_US) return -1;
    for (int i = 0; i < 4; i++)
        if (!S.per[i].fn) { S.per[i].fn = fn; S.per[i].ctx = ctx; S.per[i].period_us = period_us; S.per[i].next_us = S.now_us + period_us; return i; }
    return -1;
}
void host_sim_set_reset_cause(pal_reset_cause_t c) { S.reset = c; }
void host_sim_fail_next(host_sim_fail_t w, unsigned n) { if (w < HS_FAIL_COUNT) S.fail[w] = n; }

uint16_t host_sim_uart_take_tx(pal_id_t id, uint8_t *buf, uint16_t max)
{
    if (id >= BOARD_UART_COUNT) return 0;
    uint16_t n = S.uart[id].tx_n < max ? S.uart[id].tx_n : max;
    memcpy(buf, S.uart[id].tx, n);
    memmove(S.uart[id].tx, S.uart[id].tx + n, S.uart[id].tx_n - n);
    S.uart[id].tx_n -= n;
    return n;
}

void host_sim_uart_inject_rx(pal_id_t id, const uint8_t *buf, uint16_t len)
{
    if (id >= BOARD_UART_COUNT) return;
    uint16_t room = (uint16_t)(UART_BUF - S.uart[id].rx_n);
    if (len > room) len = room;
    memcpy(S.uart[id].rx + S.uart[id].rx_n, buf, len);
    S.uart[id].rx_n += len;
}

unsigned host_sim_events(host_sim_ev_t *out, unsigned max)
{
    unsigned n = S.ev_n < max ? S.ev_n : max;
    if (out) memcpy(out, S.ev, n * sizeof *out);
    S.ev_n = 0;
    return n;
}

/* ---------------------------------------------------------------- pal 实现 */
dz_err_t pal_init(void) { if (S.inited) return DZ_ESTATE; S.inited = true; return DZ_OK; }
const char *pal_board_name(void) { return g_board_name; }
pal_reset_cause_t pal_reset_cause(void) { return S.reset; }
/* 看门狗桩：记下超时和最近一次喂狗；到期不真复位（进程里没法复位），由测试/仿真主循环用 host_sim_wdg_bitten() 查 */
dz_err_t pal_wdg_start(uint32_t timeout_ms)
{
    if (S.wdg_ms) return DZ_ESTATE;
    if (timeout_ms == 0u || timeout_ms > 26000u) return DZ_EINVAL;     /* 与 STM32 IWDG 32 kHz 上限一致 */
    S.wdg_ms = timeout_ms; S.wdg_kick_us = S.now_us; S.wdg_bit = false;
    return DZ_OK;
}
void pal_wdg_kick(void) { if (S.wdg_ms && !S.wdg_bit) S.wdg_kick_us = S.now_us; }
bool host_sim_wdg_bitten(void)
{
    if (S.wdg_ms && S.now_us - S.wdg_kick_us > (uint64_t)S.wdg_ms * 1000u) S.wdg_bit = true;
    return S.wdg_bit;
}
uint32_t host_sim_wdg_timeout_ms(void) { return S.wdg_ms; }
uint32_t pal_irq_save(void) { return 0; }
void pal_irq_restore(uint32_t s) { (void)s; }

uint32_t pal_millis(void) { return (uint32_t)(S.now_us / 1000u); }
uint32_t pal_micros(void) { return (uint32_t)S.now_us; }
void pal_delay_us(uint32_t us) { host_sim_run_us(us); }
void pal_delay_ms(uint32_t ms) { host_sim_run_us((uint64_t)ms * 1000u); }

dz_err_t pal_gpio_write(pal_id_t id, bool a)
{
    if (id >= BOARD_GPIO_COUNT) return DZ_ENODEV;
    if (take_fail(HS_FAIL_GPIO)) return DZ_EIO;
    S.gpio[id] = a; log_ev(HS_EV_GPIO, id, a);
    return DZ_OK;
}
void host_sim_gpio_read_hook(host_sim_gpio_read_cb_t cb, void *ctx) { g_rd_cb = cb; g_rd_ctx = ctx; }

dz_err_t pal_gpio_read(pal_id_t id, bool *a)
{
    if (id >= BOARD_GPIO_COUNT) return DZ_ENODEV;
    if (!a) return DZ_EINVAL;
    if (take_fail(HS_FAIL_GPIO)) return DZ_EIO;
    *a = g_rd_cb ? g_rd_cb(id, S.gpio, g_rd_ctx) : S.gpio[id];
    return DZ_OK;
}
dz_err_t pal_gpio_toggle(pal_id_t id)
{
    if (id >= BOARD_GPIO_COUNT) return DZ_ENODEV;
    return pal_gpio_write(id, !S.gpio[id]);
}

dz_err_t pal_pwm_set_duty(pal_id_t id, uint16_t d)
{
    if (id >= BOARD_PWM_COUNT) return DZ_ENODEV;
    if (d > PAL_DUTY_MAX) return DZ_EINVAL;
    if (take_fail(HS_FAIL_PWM)) return DZ_EIO;
    S.pwm[id] = d; log_ev(HS_EV_PWM, id, d);
    return DZ_OK;
}
dz_err_t pal_pwm_set_pulse_us(pal_id_t id, uint32_t us)
{
    if (id >= BOARD_PWM_COUNT) return DZ_ENODEV;
    uint32_t period_us = 1000000u / g_host_pwm_freq[id];
    if (us > period_us) return DZ_EINVAL;
    return pal_pwm_set_duty(id, (uint16_t)((uint64_t)us * PAL_DUTY_MAX / period_us));
}
dz_err_t pal_pwm_get_freq(pal_id_t id, uint32_t *f)
{
    if (id >= BOARD_PWM_COUNT) return DZ_ENODEV;
    if (!f) return DZ_EINVAL;
    *f = g_host_pwm_freq[id];
    return DZ_OK;
}

/* 三相 PWM：仿真里三路同时生效；host_sim_pwm3_edge_aligned 模拟“定时器忘了配中心对齐” */
extern const pal_pwm3_map_t g_pal_pwm3[];
static bool s_pwm3_edge;
static uint32_t s_pwm3_updates;
void host_sim_pwm3_edge_aligned(bool on) { s_pwm3_edge = on; }
uint32_t host_sim_pwm3_updates(void) { return s_pwm3_updates; }
dz_err_t pal_pwm3_set(pal_id_t id, uint16_t u, uint16_t v, uint16_t w)
{
    if (id >= BOARD_PWM3_COUNT) return DZ_ENODEV;
    if (u > PAL_DUTY_MAX || v > PAL_DUTY_MAX || w > PAL_DUTY_MAX) return DZ_EINVAL;
    const pal_id_t *ph = g_pal_pwm3[id].ph;
    uint16_t d[3] = { u, v, w };
    for (int i = 0; i < 3; i++) { S.pwm[ph[i]] = d[i]; log_ev(HS_EV_PWM, ph[i], d[i]); }
    s_pwm3_updates++;
    return DZ_OK;
}
dz_err_t pal_pwm3_check(pal_id_t id)
{
    if (id >= BOARD_PWM3_COUNT) return DZ_ENODEV;
    return s_pwm3_edge ? DZ_ESTATE : DZ_OK;
}

dz_err_t pal_enc_get_count(pal_id_t id, int32_t *c)
{
    if (id >= BOARD_ENCODER_COUNT) return DZ_ENODEV;
    if (!c) return DZ_EINVAL;
    if (take_fail(HS_FAIL_ENC)) return DZ_EIO;
    *c = S.enc[id];
    return DZ_OK;
}
dz_err_t pal_enc_reset(pal_id_t id)
{
    if (id >= BOARD_ENCODER_COUNT) return DZ_ENODEV;
    S.enc[id] = 0; S.enc_frac[id] = 0;
    return DZ_OK;
}

dz_err_t pal_uart_write(pal_id_t id, const uint8_t *buf, uint16_t len)
{
    if (id >= BOARD_UART_COUNT) return DZ_ENODEV;
    if (!buf && len) return DZ_EINVAL;
    if (take_fail(HS_FAIL_UART)) return DZ_EIO;
    if (S.uart[id].busy) return DZ_EBUSY;
    if (len > UART_BUF - S.uart[id].tx_n) return DZ_EBUSY;
    memcpy(S.uart[id].tx + S.uart[id].tx_n, buf, len);
    S.uart[id].tx_n += len;
    return DZ_OK;
}
dz_err_t pal_uart_tx_idle(pal_id_t id, bool *idle)
{
    if (id >= BOARD_UART_COUNT) return DZ_ENODEV;
    if (!idle) return DZ_EINVAL;
    *idle = !S.uart[id].busy;
    return DZ_OK;
}
dz_err_t pal_uart_read(pal_id_t id, uint8_t *buf, uint16_t max, uint16_t *got)
{
    if (id >= BOARD_UART_COUNT) return DZ_ENODEV;
    if (!got || (!buf && max)) return DZ_EINVAL;
    if (take_fail(HS_FAIL_UART)) return DZ_EIO;
    uint16_t n = S.uart[id].rx_n < max ? S.uart[id].rx_n : max;
    memcpy(buf, S.uart[id].rx, n);
    memmove(S.uart[id].rx, S.uart[id].rx + n, S.uart[id].rx_n - n);
    S.uart[id].rx_n -= n;
    *got = n;
    return DZ_OK;
}
dz_err_t pal_uart_rx_dropped(pal_id_t id, uint32_t *d)
{
    if (id >= BOARD_UART_COUNT) return DZ_ENODEV;
    if (!d) return DZ_EINVAL;
    *d = 0;
    return DZ_OK;
}

dz_err_t pal_timer_start(pal_id_t id, uint32_t period_us, pal_timer_cb_t cb, void *ctx)
{
    if (id >= BOARD_TIMER_COUNT) return DZ_ENODEV;
    if (!cb || period_us == 0 || period_us % HOST_SIM_STEP_US) return DZ_EINVAL;
    S.tmr[id].cb = cb; S.tmr[id].ctx = ctx; S.tmr[id].period_us = period_us;
    S.tmr[id].next_us = S.now_us + period_us;
    return DZ_OK;
}
dz_err_t pal_timer_stop(pal_id_t id)
{
    if (id >= BOARD_TIMER_COUNT) return DZ_ENODEV;
    S.tmr[id].cb = 0;
    return DZ_OK;
}

dz_err_t pal_adc_read(pal_id_t id, uint16_t *raw)
{
    if (id >= BOARD_ADC_COUNT) return DZ_ENODEV;
    if (!raw) return DZ_EINVAL;
    if (take_fail(HS_FAIL_ADC)) return DZ_EIO;
    *raw = S.adc[id];
    return DZ_OK;
}
dz_err_t pal_adc_info(pal_id_t id, pal_adc_info_t *info)
{
    if (id >= BOARD_ADC_COUNT) return DZ_ENODEV;
    if (!info) return DZ_EINVAL;
    *info = g_host_adc_info[id];
    return DZ_OK;
}

/* ---- I2C / SPI：转发给 tests 挂载的假芯片；没挂 = 总线上没人应答 */
void host_sim_i2c_attach(pal_id_t id, host_sim_i2c_fn fn, void *ctx) { if (id < BOARD_I2C_COUNT) { S.i2c[id].fn = fn; S.i2c[id].ctx = ctx; } }
void host_sim_spi_attach(pal_id_t id, host_sim_spi_fn fn, void *ctx) { if (id < BOARD_SPI_COUNT) { S.spi[id].fn = fn; S.spi[id].ctx = ctx; } }
dz_err_t pal_i2c_mem_read(pal_id_t id, uint8_t addr7, uint8_t reg, uint8_t *buf, uint16_t n)
{
    if (id >= BOARD_I2C_COUNT) return DZ_ENODEV;
    if (!buf || !n || n > 255u || addr7 > 0x7Fu) return DZ_EINVAL;
    if (take_fail(HS_FAIL_I2C)) return DZ_ETIMEOUT;
    return S.i2c[id].fn ? S.i2c[id].fn(S.i2c[id].ctx, addr7, reg, buf, n, false) : DZ_EIO;
}
dz_err_t pal_i2c_mem_write(pal_id_t id, uint8_t addr7, uint8_t reg, const uint8_t *buf, uint16_t n)
{
    uint8_t tmp[32];
    if (id >= BOARD_I2C_COUNT) return DZ_ENODEV;
    if ((!buf && n) || n > sizeof tmp || addr7 > 0x7Fu) return DZ_EINVAL;
    if (take_fail(HS_FAIL_I2C)) return DZ_ETIMEOUT;
    if (n) memcpy(tmp, buf, n);
    return S.i2c[id].fn ? S.i2c[id].fn(S.i2c[id].ctx, addr7, reg, tmp, n, true) : DZ_EIO;
}
dz_err_t pal_spi_xfer(pal_id_t id, const uint8_t *tx, uint8_t *rx, uint16_t n)
{
    uint8_t ff[64], sink[64];
    if (id >= BOARD_SPI_COUNT) return DZ_ENODEV;
    if (!n || n > sizeof ff) return DZ_EINVAL;
    if (take_fail(HS_FAIL_SPI)) return DZ_ETIMEOUT;
    if (!tx) { memset(ff, 0xFF, n); tx = ff; }
    if (!S.spi[id].fn) { memset(rx ? rx : sink, 0xFF, n); return DZ_OK; }   /* MISO 悬空读到 0xFF，和真板一样 */
    return S.spi[id].fn(S.spi[id].ctx, tx, rx ? rx : sink, n);
}

/* 心跳里的板 ID：仿真板用环境变量 DZ_SIM_UID（测试里模拟“两块同型号板”），没设 = 0 未知 */
uint32_t dzctl_board_uid(void);
uint32_t dzctl_board_uid(void) { const char *e = getenv("DZ_SIM_UID"); return e ? (uint32_t)strtoul(e, NULL, 0) : 0u; }

/* 掉电存储（pal 1.5.0）：8 KB、擦除单位 1 KB，按 NOR flash 行为（擦 = 0xFF，写只能把 1 变 0）。
 * 不随 host_sim_reset 清（模拟“复位后 flash 还在”）；环境变量 DZ_SIM_NVM=文件 时每次擦写后落盘、首次访问读回（模拟断电）。 */
static uint8_t s_nvm[HOST_SIM_NVM_SIZE];
static bool s_nvm_ready;
static int s_nvm_fail;
static uint32_t s_nvm_erases;

static void nvm_ready(void)
{
    const char *path;
    FILE *fp;
    if (s_nvm_ready) return;
    s_nvm_ready = true;
    memset(s_nvm, 0xFF, sizeof s_nvm);
    path = getenv("DZ_SIM_NVM");
    if (path && (fp = fopen(path, "rb")) != NULL) { (void)!fread(s_nvm, 1, sizeof s_nvm, fp); fclose(fp); }
}

static void nvm_flush(void)
{
    const char *path = getenv("DZ_SIM_NVM");
    FILE *fp;
    if (path && (fp = fopen(path, "wb")) != NULL) { fwrite(s_nvm, 1, sizeof s_nvm, fp); fclose(fp); }
}

void host_sim_nvm_wipe(void) { s_nvm_ready = false; s_nvm_fail = 0; s_nvm_erases = 0; nvm_ready(); }
void host_sim_nvm_fail_next(int n) { s_nvm_fail = n; }
uint32_t host_sim_nvm_erases(void) { return s_nvm_erases; }

dz_err_t pal_nvm_info(uint32_t *size, uint32_t *erase_unit)
{
    if (size) *size = HOST_SIM_NVM_SIZE;
    if (erase_unit) *erase_unit = HOST_SIM_NVM_UNIT;
    return DZ_OK;
}

dz_err_t pal_nvm_erase(uint32_t off, uint32_t n)
{
    nvm_ready();
    if (off % HOST_SIM_NVM_UNIT || n % HOST_SIM_NVM_UNIT || off > HOST_SIM_NVM_SIZE || n > HOST_SIM_NVM_SIZE - off) return DZ_EINVAL;
    if (s_nvm_fail > 0) { s_nvm_fail--; return DZ_EIO; }
    memset(s_nvm + off, 0xFF, n);
    s_nvm_erases += n / HOST_SIM_NVM_UNIT;
    nvm_flush();
    return DZ_OK;
}

dz_err_t pal_nvm_write(uint32_t off, const void *p, uint32_t n)
{
    const uint8_t *b = (const uint8_t *)p;
    uint32_t i;
    nvm_ready();
    if (!p || off % 8u || n % 8u || off > HOST_SIM_NVM_SIZE || n > HOST_SIM_NVM_SIZE - off) return DZ_EINVAL;
    if (s_nvm_fail > 0) { s_nvm_fail--; return DZ_EIO; }
    for (i = 0; i < n; i++) s_nvm[off + i] &= b[i];
    nvm_flush();
    return DZ_OK;
}

dz_err_t pal_nvm_read(uint32_t off, void *p, uint32_t n)
{
    nvm_ready();
    if (!p || off > HOST_SIM_NVM_SIZE || n > HOST_SIM_NVM_SIZE - off) return DZ_EINVAL;
    memcpy(p, s_nvm + off, n);
    return DZ_OK;
}

/* ---------- ADC 块采样（软件定时，PAL 1.6.0）+ DAC ---------- */
#include "pal_adc_block.inc"
extern const pal_dac_info_t g_host_dac_info[];   /* board_gen.c，按 board.yaml bits/vref_mv */
static uint16_t s_dac[BOARD_DAC_COUNT + 1];
dz_err_t pal_dac_write(pal_id_t id, uint16_t code)
{
    if (id >= BOARD_DAC_COUNT) return DZ_ENODEV;
    if (code >= (1u << g_host_dac_info[id].bits)) return DZ_EINVAL;
    s_dac[id] = code;
    return DZ_OK;
}
dz_err_t pal_dac_info(pal_id_t id, pal_dac_info_t *info)
{
    if (id >= BOARD_DAC_COUNT) return DZ_ENODEV;
    if (!info) return DZ_EINVAL;
    *info = g_host_dac_info[id];
    return DZ_OK;
}
uint16_t host_sim_dac_get(pal_id_t id) { return id < BOARD_DAC_COUNT ? s_dac[id] : 0u; }
