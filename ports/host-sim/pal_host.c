/**
 * @file pal_host.c
 * @brief pal.h 的 PC 仿真实现。资源数量来自生成的 board_gen.h（boards/host-sim/board.yaml）。
 */
#include <string.h>
#include "board_gen.h"
#include "host_sim.h"

#define MAX_MOTORS 4
#define UART_BUF   4096

extern const char *const g_board_name;

static struct {
    bool inited;
    uint64_t now_us;
    pal_reset_cause_t reset;
    bool gpio[BOARD_GPIO_COUNT + 1];
    uint16_t pwm[BOARD_PWM_COUNT + 1];
    int32_t enc[BOARD_ENCODER_COUNT + 1];
    float enc_frac[BOARD_ENCODER_COUNT + 1];
    uint16_t adc[BOARD_ADC_COUNT + 1];
    struct { uint8_t tx[UART_BUF]; uint16_t tx_n; uint8_t rx[UART_BUF]; uint16_t rx_n; bool busy; } uart[BOARD_UART_COUNT + 1];
    struct { pal_timer_cb_t cb; void *ctx; uint32_t period_us; uint64_t next_us; } tmr[BOARD_TIMER_COUNT + 1];
    host_sim_motor_t motor[MAX_MOTORS];
    float speed[MAX_MOTORS];
    int motors;
    host_sim_ev_t ev[256];
    unsigned ev_n;
    unsigned fail[HS_FAIL_COUNT];
} S;

static bool take_fail(host_sim_fail_t w) { if (S.fail[w]) { S.fail[w]--; return true; } return false; }
static void log_ev(host_sim_ev_type_t t, pal_id_t id, uint32_t v)
{
    if (S.ev_n < sizeof S.ev / sizeof S.ev[0]) S.ev[S.ev_n++] = (host_sim_ev_t){ t, id, v };
}

/* ---------------------------------------------------------------- 仿真控制 */
void host_sim_reset(void) { memset(&S, 0, sizeof S); }
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
void host_sim_gpio_set_input(pal_id_t id, bool a) { if (id < BOARD_GPIO_COUNT) S.gpio[id] = a; }
uint16_t host_sim_pwm_duty(pal_id_t id) { return id < BOARD_PWM_COUNT ? S.pwm[id] : 0; }
void host_sim_enc_add(pal_id_t id, int32_t c) { if (id < BOARD_ENCODER_COUNT) S.enc[id] = (int32_t)((uint32_t)S.enc[id] + (uint32_t)c); }
void host_sim_adc_set(pal_id_t id, uint16_t r) { if (id < BOARD_ADC_COUNT) S.adc[id] = r; }
void host_sim_uart_set_busy(pal_id_t id, bool b) { if (id < BOARD_UART_COUNT) S.uart[id].busy = b; }
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
dz_err_t pal_gpio_read(pal_id_t id, bool *a)
{
    if (id >= BOARD_GPIO_COUNT) return DZ_ENODEV;
    if (!a) return DZ_EINVAL;
    if (take_fail(HS_FAIL_GPIO)) return DZ_EIO;
    *a = S.gpio[id];
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
    /* 仿真板 PWM 固定 20 kHz（周期 50 µs） */
    if (us > 50u) return DZ_EINVAL;
    return pal_pwm_set_duty(id, (uint16_t)(us * PAL_DUTY_MAX / 50u));
}
dz_err_t pal_pwm_get_freq(pal_id_t id, uint32_t *f)
{
    if (id >= BOARD_PWM_COUNT) return DZ_ENODEV;
    if (!f) return DZ_EINVAL;
    *f = 20000u;
    return DZ_OK;
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
    *info = (pal_adc_info_t){ 12u, 3300u, 1u, 1u };
    return DZ_OK;
}
