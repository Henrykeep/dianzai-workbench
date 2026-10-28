/**
 * @file pal_mspm0.c
 * @brief PAL 的 MSPM0 实现（SysConfig + DriverLib）。只调用 DriverLib，不做 SysConfig 已做的外设配置。
 *
 * 【未验证】整个文件只做过交叉编译（arm-none-eabi-gcc，MSPM0G3507），没有上板。重点待测：
 *  - PWM 占空比与比较值的关系（下面按 TI 例程“边沿对齐、递减计数、CC = 周期 × (1 − 占空比)”实现）；
 *  - QEI 计数方向、GPIO 软件解码在高转速下是否丢沿；
 *  - UART TX 中断在未开 FIFO 时的触发条件。
 *
 * 前提：
 *  - SysTick 由本层配置为 1 ms（SysConfig 里不要再启用 SysTick）；
 *  - 节拍定时器在 SysConfig 中为 Periodic、开 ZERO 中断、计数时钟为整 MHz（TIMER_<名>_INST_CLK_FREQ）；
 *  - 串口开 RX 中断（本层再按需开关 TX 中断），不使用 DMA；
 *  - ADC：每个 ADC12 外设一个 SysConfig 实例 ADC12_<n>（单次、软件触发）。
 */
#include <string.h>
#include "port_mspm0.h"
#include "board_gen.h"
#include "dz_wrap.h"


static m0_diag_t s_diag;
const m0_diag_t *m0_diag(void) { return &s_diag; }

/* ---------- 时基：SysTick 1 ms 中断 + 读当前值得到微秒 ---------- */
static volatile uint32_t s_ms;
static uint32_t s_systick_load;
void SysTick_Handler(void) { s_ms++; }

/* 心跳里的板 ID：FACTORYREGION（0x41C40000，只读）TRACEID 量产片每颗唯一，再混 USERID（区分料号/封装）。
 * 出处：MSPM0G350x 数据手册 SLASEX6 §8.35 Identification（DEVICEID 0x41C40004、USERID 0x41C40008）；
 * SDK dl_factoryregion.h DL_FactoryRegion_getTraceID()（读前关指令缓存）；TI E2E 1302805：预量产片 TRACEID 可能为 0/重复。 */
uint32_t dzctl_board_uid(void);   /* 声明在 dzctl.h；端口不依赖 proto 层，这里只覆盖弱定义 */
uint32_t dzctl_board_uid(void)
{
    uint32_t t = DL_FactoryRegion_getTraceID();
    if (t == 0u) return 0u;                       /* 预量产片：报“未知”，上位机退回旧规则，不会误认 */
    uint32_t u = t ^ (FACTORYREGION->USERID * 0x9E3779B1u);
    return u ? u : 1u;
}

uint32_t pal_millis(void) { return s_ms; }
uint32_t pal_micros(void)
{
    uint32_t ms, ms2, val, load = s_systick_load;
    do {
        ms = s_ms;
        val = DL_SYSTICK_getValue();
        ms2 = s_ms;
    } while (ms != ms2);
    /* DZ-REG-OK: 关中断上下文中 SysTick 已回绕但中断挂起时补 1 ms，DriverLib 无对应接口（CMSIS 内核寄存器） */
    if ((SCB->ICSR & SCB_ICSR_PENDSTSET_Msk) && val > load / 2u) ms++;
    return ms * 1000u + ((load - 1u - val) * 1000u) / load;
}
void pal_delay_us(uint32_t us) { uint32_t t0 = pal_micros(); while (pal_micros() - t0 < us) { } }
void pal_delay_ms(uint32_t ms) { pal_delay_us(ms * 1000u); }

uint32_t pal_irq_save(void) { uint32_t p = __get_PRIMASK(); __disable_irq(); return p; }
void pal_irq_restore(uint32_t s) { if (!s) __enable_irq(); }

/* ---------- 状态 ---------- */
#if BOARD_ENCODER_COUNT > 0
static uint16_t s_enc_last[BOARD_ENCODER_COUNT];
static volatile int32_t s_enc_acc[BOARD_ENCODER_COUNT];
static uint8_t  s_enc_ab[BOARD_ENCODER_COUNT];
#endif
#if BOARD_UART_COUNT > 0
static volatile uint16_t s_rx_head[BOARD_UART_COUNT], s_rx_tail[BOARD_UART_COUNT];
static volatile uint16_t s_tx_head[BOARD_UART_COUNT], s_tx_tail[BOARD_UART_COUNT];
static volatile uint32_t s_rx_dropped[BOARD_UART_COUNT];
#endif
#if BOARD_TIMER_COUNT > 0
static pal_timer_cb_t s_tmr_cb[BOARD_TIMER_COUNT];
static void          *s_tmr_ctx[BOARD_TIMER_COUNT];
#endif
static bool s_started;

#if BOARD_ENCODER_COUNT > 0
static uint8_t enc_ab(const m0_enc_t *e)
{
    uint32_t v = DL_GPIO_readPins(e->port, e->pin_a | e->pin_b);
    return (uint8_t)(((v & e->pin_a) ? 2u : 0u) | ((v & e->pin_b) ? 1u : 0u));
}
#endif

dz_err_t dz_m0_start(void)
{
    s_systick_load = CPUCLK_FREQ / 1000u;
    DL_SYSTICK_config(s_systick_load);
#if BOARD_PWM_COUNT > 0
    for (unsigned i = 0; i < BOARD_PWM_COUNT; i++) (void)pal_pwm_set_duty((pal_id_t)i, 0u);
#endif
#if BOARD_ENCODER_COUNT > 0
    for (unsigned i = 0; i < BOARD_ENCODER_COUNT; i++) {
        const m0_enc_t *e = &g_m0_enc[i];
        if (e->inst) {
            DL_Timer_startCounter(e->inst);
            s_enc_last[i] = (uint16_t)DL_Timer_getTimerCount(e->inst);
        } else {
            s_enc_ab[i] = enc_ab(e);
        }
    }
    NVIC_EnableIRQ(GPIOB_INT_IRQn);   /* GPIOA/GPIOB 共用 INT_GROUP1 */
#endif
#if BOARD_UART_COUNT > 0
    for (unsigned i = 0; i < BOARD_UART_COUNT; i++) {
        NVIC_ClearPendingIRQ(g_m0_uart[i].irq);
        NVIC_EnableIRQ(g_m0_uart[i].irq);
    }
#endif
    s_started = true;
    return DZ_OK;
}

dz_err_t pal_init(void) { return s_started ? DZ_OK : DZ_ESTATE; }   /* 初始化由 SYSCFG_DL_init 完成 */
const char *pal_board_name(void) { return g_board_name; }
/* TODO：按 DL_SYSCTL_getResetCause() 映射；映射表未对照 TRM 核实前一律返回 UNKNOWN（不编造） */
pal_reset_cause_t pal_reset_cause(void) { return PAL_RESET_UNKNOWN; }

/* ---------- GPIO ---------- */
dz_err_t pal_gpio_write(pal_id_t id, bool active)
{
#if BOARD_GPIO_COUNT > 0
    if (id >= BOARD_GPIO_COUNT) return DZ_ENODEV;
    const m0_gpio_t *g = &g_m0_gpio[id];
    if (active != (g->active_low != 0)) DL_GPIO_setPins(g->port, g->pin);
    else DL_GPIO_clearPins(g->port, g->pin);
    return DZ_OK;
#else
    (void)id; (void)active; return DZ_ENODEV;
#endif
}
dz_err_t pal_gpio_read(pal_id_t id, bool *active)
{
#if BOARD_GPIO_COUNT > 0
    if (id >= BOARD_GPIO_COUNT) return DZ_ENODEV;
    if (active == 0) return DZ_EINVAL;
    const m0_gpio_t *g = &g_m0_gpio[id];
    bool hi = DL_GPIO_readPins(g->port, g->pin) != 0u;
    *active = g->active_low ? !hi : hi;
    return DZ_OK;
#else
    (void)id; (void)active; return DZ_ENODEV;
#endif
}
dz_err_t pal_gpio_toggle(pal_id_t id)
{
#if BOARD_GPIO_COUNT > 0
    if (id >= BOARD_GPIO_COUNT) return DZ_ENODEV;
    DL_GPIO_togglePins(g_m0_gpio[id].port, g_m0_gpio[id].pin);
    return DZ_OK;
#else
    (void)id; return DZ_ENODEV;
#endif
}

/* ---------- GPIO 边沿中断（PAL 1.2.0）----------
 * .syscfg 里引脚只需设成输入；attach 时运行时设 RISE_FALL 极性、清标志、开引脚中断和 GROUP1 NVIC。
 * 边沿按逻辑电平在软件里过滤（中断入口读一次电平；脉宽短于中断延迟（几 us）时可能读错，HC-SR04 回波 ≥ 100 us 无影响）。
 * 中断入口：board_gen.c 生成的 GROUP1_IRQHandler 调 dz_m0_gpio_irq_isr()。【编译】未上板。 */
#if BOARD_GPIO_COUNT > 0
static struct { pal_gpio_irq_cb_t cb; void *ctx; uint8_t edge; } s_girq[BOARD_GPIO_COUNT];
#endif
void dz_m0_gpio_irq_isr(void)
{
#if BOARD_GPIO_COUNT > 0
    uint32_t t = pal_micros();
    for (unsigned i = 0; i < BOARD_GPIO_COUNT; i++) {
        if (!s_girq[i].cb) continue;
        const m0_gpio_t *g = &g_m0_gpio[i];
        if (!DL_GPIO_getEnabledInterruptStatus(g->port, g->pin)) continue;
        DL_GPIO_clearInterruptStatus(g->port, g->pin);
        bool hi = DL_GPIO_readPins(g->port, g->pin) != 0u;
        bool lv = g->active_low ? !hi : hi;
        if (s_girq[i].edge & (lv ? PAL_EDGE_RISING : PAL_EDGE_FALLING)) s_girq[i].cb(s_girq[i].ctx, lv, t);
    }
#endif
}
dz_err_t pal_gpio_irq_attach(pal_id_t id, pal_edge_t edge, pal_gpio_irq_cb_t cb, void *ctx)
{
#if BOARD_GPIO_COUNT > 0
    if (id >= BOARD_GPIO_COUNT) return DZ_ENODEV;
    if (!cb || edge < PAL_EDGE_RISING || edge > PAL_EDGE_BOTH) return DZ_EINVAL;
    const m0_gpio_t *g = &g_m0_gpio[id];
    unsigned n = 0;
    while (n < 31u && !(g->pin & (1u << n))) n++;
    DL_GPIO_disableInterrupt(g->port, g->pin);
    s_girq[id].ctx = ctx; s_girq[id].edge = (uint8_t)edge; s_girq[id].cb = cb;
    /* 2 位/脚，3 = RISE_FALL；DriverLib 的 set*PinsPolarity 是“或”写入，正好把该脚两位都置上 */
    if (n < 16u) DL_GPIO_setLowerPinsPolarity(g->port, 3u << (2u * n));
    else DL_GPIO_setUpperPinsPolarity(g->port, 3u << (2u * (n - 16u)));
    DL_GPIO_clearInterruptStatus(g->port, g->pin);
    DL_GPIO_enableInterrupt(g->port, g->pin);
    NVIC_EnableIRQ(GPIOB_INT_IRQn);   /* GPIOA/GPIOB 共用 INT_GROUP1 */
    return DZ_OK;
#else
    (void)id; (void)edge; (void)cb; (void)ctx; return DZ_ENODEV;
#endif
}
dz_err_t pal_gpio_irq_detach(pal_id_t id)
{
#if BOARD_GPIO_COUNT > 0
    if (id >= BOARD_GPIO_COUNT) return DZ_ENODEV;
    DL_GPIO_disableInterrupt(g_m0_gpio[id].port, g_m0_gpio[id].pin);
    s_girq[id].cb = 0;
    return DZ_OK;
#else
    (void)id; return DZ_ENODEV;
#endif
}

/* ---------- PWM（频率由 SysConfig 的周期决定，本层只写比较值） ---------- */
#if BOARD_PWM_COUNT > 0
static uint32_t pwm_top(const m0_pwm_t *p) { return DL_Timer_getLoadValue(p->inst) + 1u; }
static void pwm_set_high_ticks(const m0_pwm_t *p, uint32_t high)
{
    /* 【未验证】TI 例程约定：边沿对齐递减计数，计数器 < CC 时输出有效，故 CC = top − 高电平计数 */
    DL_Timer_setCaptureCompareValue(p->inst, pwm_top(p) - high, p->cc);
}
#endif
dz_err_t pal_pwm_set_duty(pal_id_t id, uint16_t duty)
{
#if BOARD_PWM_COUNT > 0
    if (id >= BOARD_PWM_COUNT) return DZ_ENODEV;
    if (duty > PAL_DUTY_MAX) return DZ_EINVAL;
    const m0_pwm_t *p = &g_m0_pwm[id];
    pwm_set_high_ticks(p, (uint32_t)(((uint64_t)pwm_top(p) * duty) / PAL_DUTY_MAX));
    return DZ_OK;
#else
    (void)id; (void)duty; return DZ_ENODEV;
#endif
}
dz_err_t pal_pwm_set_pulse_us(pal_id_t id, uint32_t pulse_us)
{
#if BOARD_PWM_COUNT > 0
    if (id >= BOARD_PWM_COUNT) return DZ_ENODEV;
    const m0_pwm_t *p = &g_m0_pwm[id];
    uint64_t ticks = (uint64_t)p->clk_hz * pulse_us / 1000000u;
    if (ticks > pwm_top(p)) return DZ_EINVAL;
    pwm_set_high_ticks(p, (uint32_t)ticks);
    return DZ_OK;
#else
    (void)id; (void)pulse_us; return DZ_ENODEV;
#endif
}
dz_err_t pal_pwm_get_freq(pal_id_t id, uint32_t *freq_hz)
{
#if BOARD_PWM_COUNT > 0
    if (id >= BOARD_PWM_COUNT) return DZ_ENODEV;
    if (freq_hz == 0) return DZ_EINVAL;
    *freq_hz = g_m0_pwm[id].clk_hz / pwm_top(&g_m0_pwm[id]);
    return DZ_OK;
#else
    (void)id; (void)freq_hz; return DZ_ENODEV;
#endif
}

/* ---------- 编码器：QEI（16 位扩展到 32 位）或 GPIO 软件 4 倍频 ---------- */
void dz_m0_gpio_enc_isr(void)
{
#if BOARD_ENCODER_COUNT > 0
    /* 格雷码状态转移表：下标 = (旧AB << 2) | 新AB；±1 为一步，0 为无变化或非法跳变（两相同时变 = 丢沿） */
    static const int8_t k_step[16] = { 0, -1, +1, 0, +1, 0, 0, -1, -1, 0, 0, +1, 0, +1, -1, 0 };
    for (unsigned i = 0; i < BOARD_ENCODER_COUNT; i++) {
        const m0_enc_t *e = &g_m0_enc[i];
        if (e->inst) continue;
        uint32_t hit = DL_GPIO_getEnabledInterruptStatus(e->port, e->pin_a | e->pin_b);
        if (!hit) continue;
        DL_GPIO_clearInterruptStatus(e->port, hit);
        uint8_t ab = enc_ab(e);
        uint8_t idx = (uint8_t)((s_enc_ab[i] << 2) | ab);
        if (ab != s_enc_ab[i] && k_step[idx] == 0) s_diag.enc_glitch++;
        int32_t d = k_step[idx];
        s_enc_acc[i] += e->invert ? -d : d;
        s_enc_ab[i] = ab;
    }
#endif
}
dz_err_t pal_enc_get_count(pal_id_t id, int32_t *count)
{
#if BOARD_ENCODER_COUNT > 0
    if (id >= BOARD_ENCODER_COUNT) return DZ_ENODEV;
    if (count == 0) return DZ_EINVAL;
    const m0_enc_t *e = &g_m0_enc[id];
    uint32_t st = pal_irq_save();
    if (e->inst) {
        uint16_t raw = (uint16_t)DL_Timer_getTimerCount(e->inst);
        int32_t d = dz_wrap16_delta(raw, s_enc_last[id]);   /* TIMG8 QEI 只有 16 位 */
        s_enc_last[id] = raw;
        s_enc_acc[id] += e->invert ? -d : d;
    }
    *count = s_enc_acc[id];
    pal_irq_restore(st);
    return DZ_OK;
#else
    (void)id; (void)count; return DZ_ENODEV;
#endif
}
dz_err_t pal_enc_reset(pal_id_t id)
{
#if BOARD_ENCODER_COUNT > 0
    if (id >= BOARD_ENCODER_COUNT) return DZ_ENODEV;
    uint32_t st = pal_irq_save();
    if (g_m0_enc[id].inst) s_enc_last[id] = (uint16_t)DL_Timer_getTimerCount(g_m0_enc[id].inst);
    s_enc_acc[id] = 0;
    pal_irq_restore(st);
    return DZ_OK;
#else
    (void)id; return DZ_ENODEV;
#endif
}

/* ---------- UART：RX/TX 中断 + 软件环形缓冲（head 写、tail 读，各留一格区分满/空） ---------- */
#if BOARD_UART_COUNT > 0
static void uart_tx_fill(unsigned i)
{
    const m0_uart_t *u = &g_m0_uart[i];
    while (s_tx_tail[i] != s_tx_head[i] && !DL_UART_isTXFIFOFull(u->inst)) {
        DL_UART_Main_transmitData(u->inst, u->tx_buf[s_tx_tail[i]]);
        s_tx_tail[i] = (uint16_t)((s_tx_tail[i] + 1u) % u->tx_size);
    }
    if (s_tx_tail[i] == s_tx_head[i]) DL_UART_Main_disableInterrupt(u->inst, DL_UART_MAIN_INTERRUPT_TX);
}
#endif
void dz_m0_uart_isr(unsigned i)
{
#if BOARD_UART_COUNT > 0
    const m0_uart_t *u = &g_m0_uart[i];
    for (;;) {
        switch (DL_UART_Main_getPendingInterrupt(u->inst)) {
        case DL_UART_MAIN_IIDX_RX:
            while (!DL_UART_isRXFIFOEmpty(u->inst)) {
                uint8_t b = DL_UART_Main_receiveData(u->inst);
                uint16_t n = (uint16_t)((s_rx_head[i] + 1u) % u->rx_size);
                if (n == s_rx_tail[i]) { s_rx_dropped[i]++; continue; }
                u->rx_buf[s_rx_head[i]] = b;
                s_rx_head[i] = n;
            }
            break;
        case DL_UART_MAIN_IIDX_TX:
            uart_tx_fill(i);
            break;
        case DL_UART_MAIN_IIDX_NO_INTERRUPT:
            return;
        default:
            s_diag.uart_err++;
            break;
        }
    }
#else
    (void)i;
#endif
}
dz_err_t pal_uart_write(pal_id_t id, const uint8_t *buf, uint16_t len)
{
#if BOARD_UART_COUNT > 0
    if (id >= BOARD_UART_COUNT) return DZ_ENODEV;
    if (buf == 0 && len) return DZ_EINVAL;
    const m0_uart_t *u = &g_m0_uart[id];
    if (len >= u->tx_size) return DZ_EINVAL;
    if (len == 0) return DZ_OK;
    uint32_t st = pal_irq_save();
    uint16_t used = (uint16_t)((s_tx_head[id] + u->tx_size - s_tx_tail[id]) % u->tx_size);
    if ((uint16_t)(u->tx_size - 1u - used) < len) { pal_irq_restore(st); return DZ_EBUSY; }
    for (uint16_t k = 0; k < len; k++) {
        u->tx_buf[s_tx_head[id]] = buf[k];
        s_tx_head[id] = (uint16_t)((s_tx_head[id] + 1u) % u->tx_size);
    }
    uart_tx_fill(id);
    if (s_tx_tail[id] != s_tx_head[id]) DL_UART_Main_enableInterrupt(u->inst, DL_UART_MAIN_INTERRUPT_TX);
    pal_irq_restore(st);
    return DZ_OK;
#else
    (void)id; (void)buf; (void)len; return DZ_ENODEV;
#endif
}
dz_err_t pal_uart_tx_idle(pal_id_t id, bool *idle)
{
#if BOARD_UART_COUNT > 0
    if (id >= BOARD_UART_COUNT) return DZ_ENODEV;
    if (idle == 0) return DZ_EINVAL;
    *idle = s_tx_tail[id] == s_tx_head[id] && !DL_UART_isBusy(g_m0_uart[id].inst);
    return DZ_OK;
#else
    (void)id; (void)idle; return DZ_ENODEV;
#endif
}
dz_err_t pal_uart_read(pal_id_t id, uint8_t *buf, uint16_t max, uint16_t *got)
{
#if BOARD_UART_COUNT > 0
    if (id >= BOARD_UART_COUNT) return DZ_ENODEV;
    if (got == 0 || (buf == 0 && max)) return DZ_EINVAL;
    const m0_uart_t *u = &g_m0_uart[id];
    uint16_t n = 0;
    while (n < max && s_rx_tail[id] != s_rx_head[id]) {
        buf[n++] = u->rx_buf[s_rx_tail[id]];
        s_rx_tail[id] = (uint16_t)((s_rx_tail[id] + 1u) % u->rx_size);
    }
    *got = n;
    return DZ_OK;
#else
    (void)id; (void)buf; (void)max; (void)got; return DZ_ENODEV;
#endif
}
dz_err_t pal_uart_rx_dropped(pal_id_t id, uint32_t *dropped)
{
#if BOARD_UART_COUNT > 0
    if (id >= BOARD_UART_COUNT) return DZ_ENODEV;
    if (dropped == 0) return DZ_EINVAL;
    *dropped = s_rx_dropped[id];
    return DZ_OK;
#else
    (void)id; (void)dropped; return DZ_ENODEV;
#endif
}

/* ---------- 节拍定时器 ---------- */
dz_err_t pal_timer_start(pal_id_t id, uint32_t period_us, pal_timer_cb_t cb, void *ctx)
{
#if BOARD_TIMER_COUNT > 0
    if (id >= BOARD_TIMER_COUNT) return DZ_ENODEV;
    if (cb == 0 || period_us == 0) return DZ_EINVAL;
    const m0_timer_t *t = &g_m0_timer[id];
    if (t->clk_hz % 1000000u) return DZ_EINVAL;        /* 需要整 MHz 计数时钟才能精确到 1 µs */
    uint64_t ticks = (uint64_t)(t->clk_hz / 1000000u) * period_us;
    if (ticks - 1u > t->max_load) return DZ_EINVAL;
    DL_Timer_stopCounter(t->inst);
    NVIC_DisableIRQ(t->irq);
    s_tmr_cb[id] = cb; s_tmr_ctx[id] = ctx;
    DL_Timer_setLoadValue(t->inst, (uint32_t)(ticks - 1u));
    DL_Timer_clearInterruptStatus(t->inst, DL_TIMER_INTERRUPT_ZERO_EVENT);
    NVIC_ClearPendingIRQ(t->irq);
    NVIC_EnableIRQ(t->irq);
    DL_Timer_startCounter(t->inst);
    return DZ_OK;
#else
    (void)id; (void)period_us; (void)cb; (void)ctx; return DZ_ENODEV;
#endif
}
dz_err_t pal_timer_stop(pal_id_t id)
{
#if BOARD_TIMER_COUNT > 0
    if (id >= BOARD_TIMER_COUNT) return DZ_ENODEV;
    DL_Timer_stopCounter(g_m0_timer[id].inst);
    NVIC_DisableIRQ(g_m0_timer[id].irq);
    s_tmr_cb[id] = 0;
    return DZ_OK;
#else
    (void)id; return DZ_ENODEV;
#endif
}
void dz_m0_timer_isr(unsigned i)
{
#if BOARD_TIMER_COUNT > 0
    if (DL_Timer_getPendingInterrupt(g_m0_timer[i].inst) == DL_TIMER_IIDX_ZERO && s_tmr_cb[i])
        s_tmr_cb[i](s_tmr_ctx[i]);
#else
    (void)i;
#endif
}

/* ---------- ADC（PAL 1.2.0）：单次软件触发、轮询 ----------
 * SysConfig 里每个用到的 ADC12 外设配一个实例 ADC12_<n>（单次、软件触发、MEM0），通道/引脚在 .syscfg 里分配；
 * 本层每次读时把 MEM0 改到该资源的通道（同一 ADC 上多路分时复用），开转换 → 软件启动 → 等 MEM0 结果 → 读结果。
 * 单次模式转换完 ENC 自动清零，所以每次都重新 enableConversions。超时 1 ms（12 位典型几 us）。【编译】未上板。 */
#if BOARD_ADC_COUNT > 0
#define M0_ADC_TIMEOUT_US 1000u
#endif
dz_err_t pal_adc_read(pal_id_t id, uint16_t *raw)
{
#if BOARD_ADC_COUNT > 0
    if (id >= BOARD_ADC_COUNT) return DZ_ENODEV;
    if (!raw) return DZ_EINVAL;
    const m0_adc_t *a = &g_m0_adc[id];
    DL_ADC12_disableConversions(a->inst);
    DL_ADC12_configConversionMem(a->inst, DL_ADC12_MEM_IDX_0, a->chansel, DL_ADC12_REFERENCE_VOLTAGE_VDDA,
        DL_ADC12_SAMPLE_TIMER_SOURCE_SCOMP0, DL_ADC12_AVERAGING_MODE_DISABLED, DL_ADC12_BURN_OUT_SOURCE_DISABLED,
        DL_ADC12_TRIGGER_MODE_AUTO_NEXT, DL_ADC12_WINDOWS_COMP_MODE_DISABLED);
    DL_ADC12_clearInterruptStatus(a->inst, DL_ADC12_INTERRUPT_MEM0_RESULT_LOADED);
    DL_ADC12_enableConversions(a->inst);
    DL_ADC12_startConversion(a->inst);
    uint32_t t0 = pal_micros();
    while (!DL_ADC12_getRawInterruptStatus(a->inst, DL_ADC12_INTERRUPT_MEM0_RESULT_LOADED)) {
        if ((uint32_t)(pal_micros() - t0) > M0_ADC_TIMEOUT_US) { s_diag.adc_timeout++; return DZ_ETIMEOUT; }
    }
    *raw = DL_ADC12_getMemResult(a->inst, DL_ADC12_MEM_IDX_0);
    DL_ADC12_clearInterruptStatus(a->inst, DL_ADC12_INTERRUPT_MEM0_RESULT_LOADED);
    return DZ_OK;
#else
    (void)id; (void)raw; return DZ_ENODEV;
#endif
}
dz_err_t pal_adc_info(pal_id_t id, pal_adc_info_t *info)
{
#if BOARD_ADC_COUNT > 0
    if (id >= BOARD_ADC_COUNT) return DZ_ENODEV;
    if (!info) return DZ_EINVAL;
    *info = g_m0_adc[id].info;
    return DZ_OK;
#else
    (void)id; (void)info; return DZ_ENODEV;
#endif
}

/* I2C / SPI：MSPM0 移植层尚未实现（需要 SysConfig 里配 I2C/SPI 外设，再用 DL_I2C_* / DL_SPI_* 写，没上板之前不写）。
 * MSPM0 主控要用 IMU 的话：走 UART 姿态模块（apps/imu_module + proto/dzimu），这条路径不依赖 I2C/SPI。 */
/* ---------- I2C（主机，轮询；PAL 1.1.0）----------
 * 流程按 TI 例程 i2c_controller_rw_multibyte_fifo_poll：等 IDLE → 填 TX FIFO → startControllerTransferAdvanced →
 * 轮询 FIFO / BUSY → 查 ERROR（地址或数据 NACK）/ ARBITRATION_LOST。读寄存器 = 写 1 字节寄存器号（不发 STOP）+ 重复起始读 n 字节。
 * 每一步都有 PAL_I2C_TIMEOUT_MS 超时，超时后 resetControllerTransfer 复位状态机。【编译】未上板验证。 */
#if BOARD_I2C_COUNT > 0
static bool m0_late(uint32_t t0) { return (uint32_t)(s_ms - t0) > PAL_I2C_TIMEOUT_MS; }

static dz_err_t i2c_wait_idle(I2C_Regs *i2c, uint32_t t0)
{
    while (!(DL_I2C_getControllerStatus(i2c) & DL_I2C_CONTROLLER_STATUS_IDLE))
        if (m0_late(t0)) return DZ_ETIMEOUT;
    return DZ_OK;
}

static dz_err_t i2c_wait_done(I2C_Regs *i2c, uint32_t t0)
{
    while (DL_I2C_getControllerStatus(i2c) & DL_I2C_CONTROLLER_STATUS_BUSY)
        if (m0_late(t0)) return DZ_ETIMEOUT;
    uint32_t st = DL_I2C_getControllerStatus(i2c);
    if (st & (DL_I2C_CONTROLLER_STATUS_ERROR | DL_I2C_CONTROLLER_STATUS_ARBITRATION_LOST)) return DZ_EIO;
    return DZ_OK;
}

static dz_err_t i2c_fail(I2C_Regs *i2c, dz_err_t e)
{
    if (e == DZ_ETIMEOUT) s_diag.i2c_timeout++; else s_diag.i2c_err++;
    DL_I2C_flushControllerTXFIFO(i2c);
    DL_I2C_flushControllerRXFIFO(i2c);
    DL_I2C_resetControllerTransfer(i2c);
    return e;
}
#endif

dz_err_t pal_i2c_mem_read(pal_id_t id, uint8_t addr7, uint8_t reg, uint8_t *buf, uint16_t n)
{
#if BOARD_I2C_COUNT > 0
    if (id >= BOARD_I2C_COUNT) return DZ_ENODEV;
    if (!buf || !n || n > 0x0FFFu || addr7 > 0x7Fu) return DZ_EINVAL;
    I2C_Regs *i2c = g_m0_i2c[id].inst;
    uint32_t t0 = s_ms;
    dz_err_t e = i2c_wait_idle(i2c, t0);
    if (e != DZ_OK) return i2c_fail(i2c, e);
    DL_I2C_flushControllerTXFIFO(i2c);
    DL_I2C_flushControllerRXFIFO(i2c);
    DL_I2C_fillControllerTXFIFO(i2c, &reg, 1u);
    DL_I2C_startControllerTransferAdvanced(i2c, addr7, DL_I2C_CONTROLLER_DIRECTION_TX, 1u,
        DL_I2C_CONTROLLER_START_ENABLE, DL_I2C_CONTROLLER_STOP_DISABLE, DL_I2C_CONTROLLER_ACK_ENABLE);
    if ((e = i2c_wait_done(i2c, t0)) != DZ_OK) return i2c_fail(i2c, e);
    DL_I2C_startControllerTransferAdvanced(i2c, addr7, DL_I2C_CONTROLLER_DIRECTION_RX, n,
        DL_I2C_CONTROLLER_START_ENABLE, DL_I2C_CONTROLLER_STOP_ENABLE, DL_I2C_CONTROLLER_ACK_DISABLE);
    for (uint16_t i = 0; i < n; i++) {
        while (DL_I2C_isControllerRXFIFOEmpty(i2c)) {
            if (DL_I2C_getControllerStatus(i2c) & DL_I2C_CONTROLLER_STATUS_ERROR) return i2c_fail(i2c, DZ_EIO);
            if (m0_late(t0)) return i2c_fail(i2c, DZ_ETIMEOUT);
        }
        buf[i] = DL_I2C_receiveControllerData(i2c);
    }
    if ((e = i2c_wait_done(i2c, t0)) != DZ_OK) return i2c_fail(i2c, e);
    return DZ_OK;
#else
    (void)id; (void)addr7; (void)reg; (void)buf; (void)n;
    return DZ_ENODEV;
#endif
}

dz_err_t pal_i2c_mem_write(pal_id_t id, uint8_t addr7, uint8_t reg, const uint8_t *buf, uint16_t n)
{
#if BOARD_I2C_COUNT > 0
    if (id >= BOARD_I2C_COUNT) return DZ_ENODEV;
    if ((!buf && n) || n > 0x0FFEu || addr7 > 0x7Fu) return DZ_EINVAL;
    I2C_Regs *i2c = g_m0_i2c[id].inst;
    uint32_t t0 = s_ms;
    dz_err_t e = i2c_wait_idle(i2c, t0);
    if (e != DZ_OK) return i2c_fail(i2c, e);
    DL_I2C_flushControllerTXFIFO(i2c);
    DL_I2C_fillControllerTXFIFO(i2c, &reg, 1u);
    uint16_t i = 0;
    while (i < n && !DL_I2C_isControllerTXFIFOFull(i2c)) DL_I2C_transmitControllerData(i2c, buf[i++]);   /* 先填满 8 字节 FIFO */
    DL_I2C_startControllerTransferAdvanced(i2c, addr7, DL_I2C_CONTROLLER_DIRECTION_TX, (uint16_t)(n + 1u),
        DL_I2C_CONTROLLER_START_ENABLE, DL_I2C_CONTROLLER_STOP_ENABLE, DL_I2C_CONTROLLER_ACK_ENABLE);
    while (i < n) {                                                                                         /* 边发边补 */
        if (!DL_I2C_isControllerTXFIFOFull(i2c)) { DL_I2C_transmitControllerData(i2c, buf[i++]); continue; }
        if (DL_I2C_getControllerStatus(i2c) & DL_I2C_CONTROLLER_STATUS_ERROR) return i2c_fail(i2c, DZ_EIO);
        if (m0_late(t0)) return i2c_fail(i2c, DZ_ETIMEOUT);
    }
    if ((e = i2c_wait_done(i2c, t0)) != DZ_OK) return i2c_fail(i2c, e);
    return DZ_OK;
#else
    (void)id; (void)addr7; (void)reg; (void)buf; (void)n;
    return DZ_ENODEV;
#endif
}

/* ---------- SPI（主机，轮询，软件片选；PAL 1.1.0）----------
 * 逐字节：等 TX FIFO 不满 → 发 → 等 RX 非空 → 收（收发严格配对，FIFO 不会溢出）。最后等 BUSY 清零再拉高片选。【编译】未上板验证。 */
dz_err_t pal_spi_xfer(pal_id_t id, const uint8_t *tx, uint8_t *rx, uint16_t n)
{
#if BOARD_SPI_COUNT > 0
    if (id >= BOARD_SPI_COUNT) return DZ_ENODEV;
    if (!n || n > 64u) return DZ_EINVAL;
    const m0_spi_t *c = &g_m0_spi[id];
    uint32_t t0 = s_ms;
    dz_err_t e = DZ_OK;
    while (!DL_SPI_isRXFIFOEmpty(c->inst)) (void)DL_SPI_receiveData8(c->inst);   /* 丢掉上次残留 */
    DL_GPIO_clearPins(c->cs_port, c->cs_pin);
    for (uint16_t i = 0; i < n && e == DZ_OK; i++) {
        while (DL_SPI_isTXFIFOFull(c->inst))
            if ((uint32_t)(s_ms - t0) > PAL_I2C_TIMEOUT_MS) { e = DZ_ETIMEOUT; break; }
        if (e != DZ_OK) break;
        DL_SPI_transmitData8(c->inst, tx ? tx[i] : 0xFFu);
        while (DL_SPI_isRXFIFOEmpty(c->inst))
            if ((uint32_t)(s_ms - t0) > PAL_I2C_TIMEOUT_MS) { e = DZ_ETIMEOUT; break; }
        if (e != DZ_OK) break;
        uint8_t b = DL_SPI_receiveData8(c->inst);
        if (rx) rx[i] = b;
    }
    while (e == DZ_OK && DL_SPI_isBusy(c->inst))
        if ((uint32_t)(s_ms - t0) > PAL_I2C_TIMEOUT_MS) e = DZ_ETIMEOUT;
    DL_GPIO_setPins(c->cs_port, c->cs_pin);
    if (e != DZ_OK) s_diag.spi_timeout++;
    return e;
#else
    (void)id; (void)tx; (void)rx; (void)n;
    return DZ_ENODEV;
#endif
}
