/**
 * @file pal_cubemx.c
 * @brief PAL 的 STM32 CubeMX 实现：只调用 HAL API，包装 CubeMX 生成的句柄，不做任何外设配置。
 *
 * 前提（tools/ioc_import.py 会检查）：
 *  - HAL 时基为 SysTick（Pinout > SYS > Timebase Source = SysTick），否则 pal_micros 不成立；
 *  - NVIC 优先级分组 4（全部抢占位）；SysTick 优先级数值 ≤ 所有用到 HAL_Delay/超时的中断；
 *  - 串口 RX DMA 为 Circular，TX DMA 为 Normal；
 *  - 编码器定时器为 Encoder Mode；PWM 定时器 PSC/ARR 已按目标频率配置（本层只改 CCR）；
 *  - CTRL 等节拍定时器打开了更新中断（本层在启动时按周期改 PSC/ARR）。
 * 与芯片系列有关的只有 timer_clock_hz() 中“定时器挂在哪条 APB 上”的判断（见注释）。
 */
#include <string.h>
#include "port_cubemx.h"
#include "board_gen.h"
#include "dz_cubemx.h"
#include "app.h"

static cm_diag_t s_diag;
const cm_diag_t *cm_diag(void) { return &s_diag; }

#if BOARD_ENCODER_COUNT > 0
static uint32_t s_enc_last[BOARD_ENCODER_COUNT];
static int32_t  s_enc_acc[BOARD_ENCODER_COUNT];
#endif
#if BOARD_UART_COUNT > 0
static volatile uint32_t s_rx_wraps[BOARD_UART_COUNT];   /* RX DMA 完整回绕次数（RxCplt 回调） */
static uint32_t s_rx_seen[BOARD_UART_COUNT];             /* 上次计算出的已写入总量（单调） */
static uint32_t s_rx_read[BOARD_UART_COUNT];
static uint32_t s_rx_dropped[BOARD_UART_COUNT];
#endif
#if BOARD_TIMER_COUNT > 0
static pal_timer_cb_t s_tmr_cb[BOARD_TIMER_COUNT];
static void          *s_tmr_ctx[BOARD_TIMER_COUNT];
#endif

/* ---------- 定时器时钟：HAL 读 PCLK 与 APB 分频，按参考手册规则 ×2 ---------- */
static uint32_t timer_clock_hz(const TIM_HandleTypeDef *h)
{
    RCC_ClkInitTypeDef c; uint32_t lat;
    HAL_RCC_GetClockConfig(&c, &lat);
#if defined(APB2PERIPH_BASE) && defined(AHB1PERIPH_BASE)
    /* F0/F1/F2/F3/F4/F7/G0/G4/L4 等：APB2 定时器地址位于 [APB2PERIPH_BASE, AHB1PERIPH_BASE)。 */
    uint32_t a = (uint32_t)h->Instance;
    bool apb2 = a >= APB2PERIPH_BASE && a < AHB1PERIPH_BASE;
#else
#error "本系列（如 H7/U5）APB 布局不同：请在此补充判断，并在 docs/05-cubemx.md 的支持系列表里登记"
#endif
    uint32_t pclk = apb2 ? HAL_RCC_GetPCLK2Freq() : HAL_RCC_GetPCLK1Freq();
    uint32_t div  = apb2 ? c.APB2CLKDivider : c.APB1CLKDivider;
    return div == RCC_HCLK_DIV1 ? pclk : pclk * 2u;
}

/* 16 位定时器 ARR 写 0xFFFFFFFF 后读回只有 0xFFFF —— 用 CubeMX 已初始化的值判断不可靠，故单独探测。 */
static bool tim_is_32bit(TIM_HandleTypeDef *h)
{
    uint32_t keep = __HAL_TIM_GET_AUTORELOAD(h);
    __HAL_TIM_SET_AUTORELOAD(h, 0xFFFFFFFFu);
    bool w = __HAL_TIM_GET_AUTORELOAD(h) > 0xFFFFu;
    __HAL_TIM_SET_AUTORELOAD(h, keep);
    return w;
}

/* ---------- 启动 ---------- */
static bool s_started;

static dz_err_t start_all(void)
{
    dz_err_t rc = DZ_OK;
#if BOARD_PWM_COUNT > 0
    for (unsigned i = 0; i < BOARD_PWM_COUNT; i++) {
        __HAL_TIM_SET_COMPARE(g_cm_pwm[i].h, g_cm_pwm[i].channel, 0u);
        if (HAL_TIM_PWM_Start(g_cm_pwm[i].h, g_cm_pwm[i].channel) != HAL_OK) rc = DZ_EIO;
    }
#endif
#if BOARD_ENCODER_COUNT > 0
    for (unsigned i = 0; i < BOARD_ENCODER_COUNT; i++) {
        if (HAL_TIM_Encoder_Start(g_cm_enc[i].h, TIM_CHANNEL_ALL) != HAL_OK) rc = DZ_EIO;
        s_enc_last[i] = __HAL_TIM_GET_COUNTER(g_cm_enc[i].h);
    }
#endif
#if BOARD_UART_COUNT > 0
    for (unsigned i = 0; i < BOARD_UART_COUNT; i++) {
        const cm_uart_t *u = &g_cm_uart[i];
        if (u->h->hdmarx == 0) { rc = DZ_EIO; continue; }   /* ioc_import 已检查；这里兜底 */
        if (HAL_UART_Receive_DMA(u->h, u->rx_buf, u->rx_size) != HAL_OK) rc = DZ_EIO;
    }
#endif
    return rc;
}

void dz_cubemx_start(void)
{
    /* DZ-REG-OK: CMSIS 内核寄存器，HAL 无打开 DWT/跟踪单元的接口（调试器看周期计数用） */
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    dz_err_t e = start_all();
    s_started = true;
    if (e == DZ_OK) e = app_init();
    if (e != DZ_OK) {
        for (;;) {
#ifdef RES_GPIO_LED
            pal_gpio_toggle(RES_GPIO_LED);
#endif
            HAL_Delay(50);
        }
    }
}

void dz_cubemx_loop(void) { app_loop(); }

/* ---------- 系统 ---------- */
dz_err_t pal_init(void) { return s_started ? DZ_OK : DZ_ESTATE; }   /* 初始化由 CubeMX 的 MX_xxx_Init 完成 */
const char *pal_board_name(void) { return g_board_name; }
pal_reset_cause_t pal_reset_cause(void)
{
#if defined(RCC_FLAG_IWDGRST) && defined(RCC_FLAG_PORRST)
    static int8_t cached = -1;
    if (cached < 0) {
        pal_reset_cause_t r = PAL_RESET_UNKNOWN;
        if (__HAL_RCC_GET_FLAG(RCC_FLAG_IWDGRST)) r = PAL_RESET_WATCHDOG;
        else if (__HAL_RCC_GET_FLAG(RCC_FLAG_SFTRST)) r = PAL_RESET_SOFTWARE;
#ifdef RCC_FLAG_BORRST
        else if (__HAL_RCC_GET_FLAG(RCC_FLAG_BORRST) && !__HAL_RCC_GET_FLAG(RCC_FLAG_PORRST)) r = PAL_RESET_BROWNOUT;
#endif
        else if (__HAL_RCC_GET_FLAG(RCC_FLAG_PORRST)) r = PAL_RESET_POWER_ON;
        else if (__HAL_RCC_GET_FLAG(RCC_FLAG_PINRST)) r = PAL_RESET_PIN;
        __HAL_RCC_CLEAR_RESET_FLAGS();
        cached = (int8_t)r;
    }
    return (pal_reset_cause_t)cached;
#else
    return PAL_RESET_UNKNOWN;
#endif
}
uint32_t pal_irq_save(void) { uint32_t p = __get_PRIMASK(); __disable_irq(); return p; }
void pal_irq_restore(uint32_t s) { if (!s) __enable_irq(); }

/* ---------- 时间（SysTick 由 CubeMX 生成的 SysTick_Handler -> HAL_IncTick 驱动） ---------- */
uint32_t pal_millis(void) { return HAL_GetTick(); }
uint32_t pal_micros(void)
{
    /* DZ-REG-OK: HAL 只提供 1 ms 节拍，微秒时间必须读 SysTick 计数（CMSIS 内核寄存器） */
    uint32_t ms, ms2, val, load = SysTick->LOAD + 1u;
    do {
        ms = HAL_GetTick();
        val = SysTick->VAL;              /* DZ-REG-OK: 同上 */
        ms2 = HAL_GetTick();
    } while (ms != ms2);
    /* DZ-REG-OK: 关中断上下文中 SysTick 已回绕但中断挂起时补 1 ms，HAL 无对应接口 */
    if ((SCB->ICSR & SCB_ICSR_PENDSTSET_Msk) && val > (load / 2u)) ms++;
    return ms * 1000u + ((load - 1u - val) * 1000u) / load;
}
void pal_delay_us(uint32_t us) { uint32_t t0 = pal_micros(); while (pal_micros() - t0 < us) { } }
void pal_delay_ms(uint32_t ms) { pal_delay_us(ms * 1000u); }

/* ---------- GPIO ---------- */
dz_err_t pal_gpio_write(pal_id_t id, bool active)
{
#if BOARD_GPIO_COUNT > 0
    if (id >= BOARD_GPIO_COUNT) return DZ_ENODEV;
    const cm_gpio_t *g = &g_cm_gpio[id];
    HAL_GPIO_WritePin(g->port, g->pin, (active != (g->active_low != 0)) ? GPIO_PIN_SET : GPIO_PIN_RESET);
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
    const cm_gpio_t *g = &g_cm_gpio[id];
    bool hi = HAL_GPIO_ReadPin(g->port, g->pin) == GPIO_PIN_SET;
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
    HAL_GPIO_TogglePin(g_cm_gpio[id].port, g_cm_gpio[id].pin);
    return DZ_OK;
#else
    (void)id; return DZ_ENODEV;
#endif
}

/* ---------- PWM（频率由 CubeMX 的 PSC/ARR 决定，本层只写比较值） ---------- */
dz_err_t pal_pwm_set_duty(pal_id_t id, uint16_t duty)
{
#if BOARD_PWM_COUNT > 0
    if (id >= BOARD_PWM_COUNT) return DZ_ENODEV;
    if (duty > PAL_DUTY_MAX) return DZ_EINVAL;
    TIM_HandleTypeDef *h = g_cm_pwm[id].h;
    uint32_t top = __HAL_TIM_GET_AUTORELOAD(h) + 1u;
    __HAL_TIM_SET_COMPARE(h, g_cm_pwm[id].channel, (uint32_t)(((uint64_t)top * duty) / PAL_DUTY_MAX));
    return DZ_OK;
#else
    (void)id; (void)duty; return DZ_ENODEV;
#endif
}
dz_err_t pal_pwm_set_pulse_us(pal_id_t id, uint32_t pulse_us)
{
#if BOARD_PWM_COUNT > 0
    if (id >= BOARD_PWM_COUNT) return DZ_ENODEV;
    TIM_HandleTypeDef *h = g_cm_pwm[id].h;
    uint64_t tick_hz = timer_clock_hz(h) / (h->Instance->PSC + 1u);  /* DZ-REG-OK: 读 PSC 当前值，HAL 只有 SET 宏无 GET 宏 */
    uint64_t cmp = tick_hz * pulse_us / 1000000u;
    if (cmp > (uint64_t)__HAL_TIM_GET_AUTORELOAD(h) + 1u) return DZ_EINVAL;
    __HAL_TIM_SET_COMPARE(h, g_cm_pwm[id].channel, (uint32_t)cmp);
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
    TIM_HandleTypeDef *h = g_cm_pwm[id].h;
    uint32_t psc = h->Instance->PSC;   /* DZ-REG-OK: 同上，读 PSC 当前值 */
    *freq_hz = (uint32_t)((uint64_t)timer_clock_hz(h) / ((uint64_t)(psc + 1u) * (__HAL_TIM_GET_AUTORELOAD(h) + 1u)));
    return DZ_OK;
#else
    (void)id; (void)freq_hz; return DZ_ENODEV;
#endif
}

/* ---------- 编码器：16/32 位定时器统一扩展为 32 位累计 ---------- */
dz_err_t pal_enc_get_count(pal_id_t id, int32_t *count)
{
#if BOARD_ENCODER_COUNT > 0
    if (id >= BOARD_ENCODER_COUNT) return DZ_ENODEV;
    if (count == 0) return DZ_EINVAL;
    static int8_t wide[BOARD_ENCODER_COUNT];   /* 0 未探测，1 = 16 位，2 = 32 位 */
    TIM_HandleTypeDef *h = g_cm_enc[id].h;
    uint32_t st = pal_irq_save();
    if (!wide[id]) wide[id] = tim_is_32bit(h) ? 2 : 1;
    uint32_t raw = __HAL_TIM_GET_COUNTER(h);
    int32_t d = wide[id] == 2 ? (int32_t)(raw - s_enc_last[id]) : (int32_t)(int16_t)(uint16_t)(raw - s_enc_last[id]);
    s_enc_last[id] = raw;
    s_enc_acc[id] = (int32_t)((uint32_t)s_enc_acc[id] + (uint32_t)(g_cm_enc[id].invert ? -d : d));
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
    s_enc_last[id] = __HAL_TIM_GET_COUNTER(g_cm_enc[id].h);
    s_enc_acc[id] = 0;
    pal_irq_restore(st);
    return DZ_OK;
#else
    (void)id; return DZ_ENODEV;
#endif
}

/* ---------- UART：RX 循环 DMA + 软件读指针；TX DMA/IT 拷贝发送 ---------- */
#if BOARD_UART_COUNT > 0
static int uart_index(const UART_HandleTypeDef *h)
{
    for (unsigned i = 0; i < BOARD_UART_COUNT; i++) if (g_cm_uart[i].h == h) return (int)i;
    return -1;
}
#endif
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *h)
{
#if BOARD_UART_COUNT > 0
    int i = uart_index(h); if (i >= 0) s_rx_wraps[i]++;
#else
    (void)h;
#endif
}
void HAL_UART_ErrorCallback(UART_HandleTypeDef *h)
{
#if BOARD_UART_COUNT > 0
    /* ORE/NE/FE 时 HAL 可能中止 DMA：整体重启，读写计数归零，丢失量未知记 1 */
    int i = uart_index(h);
    s_diag.uart_err++;
    if (i < 0) return;
    HAL_UART_AbortReceive(h);
    s_rx_dropped[i]++;
    s_rx_wraps[i] = 0; s_rx_seen[i] = 0; s_rx_read[i] = 0;
    (void)HAL_UART_Receive_DMA(h, g_cm_uart[i].rx_buf, g_cm_uart[i].rx_size);
#else
    (void)h;
#endif
}

dz_err_t pal_uart_write(pal_id_t id, const uint8_t *buf, uint16_t len)
{
#if BOARD_UART_COUNT > 0
    if (id >= BOARD_UART_COUNT) return DZ_ENODEV;
    if (buf == 0 && len) return DZ_EINVAL;
    const cm_uart_t *u = &g_cm_uart[id];
    if (len > u->tx_size) return DZ_EINVAL;
    if (len == 0) return DZ_OK;
    uint32_t st = pal_irq_save();
    if (u->h->gState != HAL_UART_STATE_READY) { pal_irq_restore(st); return DZ_EBUSY; }
    memcpy(u->tx_buf, buf, len);
    HAL_StatusTypeDef r = u->h->hdmatx ? HAL_UART_Transmit_DMA(u->h, u->tx_buf, len)
                                       : HAL_UART_Transmit_IT(u->h, u->tx_buf, len);
    pal_irq_restore(st);
    return r == HAL_OK ? DZ_OK : (r == HAL_BUSY ? DZ_EBUSY : DZ_EIO);
#else
    (void)id; (void)buf; (void)len; return DZ_ENODEV;
#endif
}
dz_err_t pal_uart_tx_idle(pal_id_t id, bool *idle)
{
#if BOARD_UART_COUNT > 0
    if (id >= BOARD_UART_COUNT) return DZ_ENODEV;
    if (idle == 0) return DZ_EINVAL;
    *idle = g_cm_uart[id].h->gState == HAL_UART_STATE_READY;
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
    const cm_uart_t *u = &g_cm_uart[id];
    const uint32_t size = u->rx_size;
    /* 已写入总量 = 回绕次数 × size + DMA 当前位置。只用 HAL 宏，不依赖各系列不同的 DMA 标志位宏。
     * 关中断期间 DMA 回绕而 RxCplt 尚未执行时，总量会比上次小 —— 此时补一个 size（总量必须单调）。
     * 前提：两次调用之间新数据不超过 size 字节（rx_buf 按“最长调用间隔 × 波特率”留够，见 docs）。 */
    uint32_t st = pal_irq_save();
    uint32_t pos = size - __HAL_DMA_GET_COUNTER(u->h->hdmarx);
    uint32_t written = s_rx_wraps[id] * size + (pos % size);
    if (written < s_rx_seen[id]) written += size;
    s_rx_seen[id] = written;
    pal_irq_restore(st);

    uint32_t unread = written - s_rx_read[id];
    if (unread > size) {
        s_rx_dropped[id] += unread - size;
        s_rx_read[id] = written - size;
        unread = size;
    }
    uint16_t n = (uint16_t)(unread < max ? unread : max);
    for (uint16_t k = 0; k < n; k++) buf[k] = u->rx_buf[(s_rx_read[id] + k) % size];
    s_rx_read[id] += n;
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
    TIM_HandleTypeDef *h = g_cm_timer[id].h;
    uint32_t clk = timer_clock_hz(h);
    if (clk % 1000000u) return DZ_EINVAL;          /* 需要整 MHz 才能 1 µs 分辨率 */
    uint32_t max_arr = tim_is_32bit(h) ? 0xFFFFFFFFu : 0xFFFFu;
    if (period_us - 1u > max_arr) return DZ_EINVAL;
    HAL_TIM_Base_Stop_IT(h);
    s_tmr_cb[id] = cb; s_tmr_ctx[id] = ctx;
    __HAL_TIM_SET_PRESCALER(h, clk / 1000000u - 1u);
    __HAL_TIM_SET_AUTORELOAD(h, period_us - 1u);
    __HAL_TIM_SET_COUNTER(h, 0u);
    (void)HAL_TIM_GenerateEvent(h, TIM_EVENTSOURCE_UPDATE);   /* 立即装载新 PSC */
    __HAL_TIM_CLEAR_FLAG(h, TIM_FLAG_UPDATE);
    return HAL_TIM_Base_Start_IT(h) == HAL_OK ? DZ_OK : DZ_EIO;
#else
    (void)id; (void)period_us; (void)cb; (void)ctx; return DZ_ENODEV;
#endif
}
dz_err_t pal_timer_stop(pal_id_t id)
{
#if BOARD_TIMER_COUNT > 0
    if (id >= BOARD_TIMER_COUNT) return DZ_ENODEV;
    HAL_TIM_Base_Stop_IT(g_cm_timer[id].h);
    s_tmr_cb[id] = 0;
    return DZ_OK;
#else
    (void)id; return DZ_ENODEV;
#endif
}
/* CubeMX 的 main.c 若已在 USER CODE 里定义了本回调会重复定义：ioc_import 会提示改用 dz 的钩子。 */
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *h)
{
#if BOARD_TIMER_COUNT > 0
    for (unsigned i = 0; i < BOARD_TIMER_COUNT; i++)
        if (g_cm_timer[i].h == h) { if (s_tmr_cb[i]) s_tmr_cb[i](s_tmr_ctx[i]); return; }
#endif
    s_diag.tim_cb_unknown++;
    (void)h;
}

/* ---------- ADC：单次软件触发；通道配置跨系列差异用 #ifdef 处理 ---------- */
dz_err_t pal_adc_read(pal_id_t id, uint16_t *raw)
{
#if BOARD_ADC_COUNT > 0
    if (id >= BOARD_ADC_COUNT) return DZ_ENODEV;
    if (raw == 0) return DZ_EINVAL;
    ADC_HandleTypeDef *h = g_cm_adc[id].h;
    ADC_ChannelConfTypeDef c = {0};
    c.Channel = g_cm_adc[id].channel;
#if defined(ADC_REGULAR_RANK_1)
    c.Rank = ADC_REGULAR_RANK_1;        /* G4/L4/H7 等 */
#else
    c.Rank = 1;                         /* F1/F4 */
#endif
#if defined(ADC_SAMPLETIME_84CYCLES)
    c.SamplingTime = ADC_SAMPLETIME_84CYCLES;
#elif defined(ADC_SAMPLETIME_92CYCLES_5)
    c.SamplingTime = ADC_SAMPLETIME_92CYCLES_5;
#elif defined(ADC_SAMPLETIME_71CYCLES_5)
    c.SamplingTime = ADC_SAMPLETIME_71CYCLES_5;
#else
#error "未知系列的 ADC 采样时间常量：请在此补充（docs/05-cubemx.md 支持系列表）"
#endif
    if (HAL_ADC_ConfigChannel(h, &c) != HAL_OK) return DZ_EIO;
    if (HAL_ADC_Start(h) != HAL_OK) return DZ_EIO;
    HAL_StatusTypeDef r = HAL_ADC_PollForConversion(h, 2);
    if (r != HAL_OK) { HAL_ADC_Stop(h); return r == HAL_TIMEOUT ? DZ_ETIMEOUT : DZ_EIO; }
    *raw = (uint16_t)HAL_ADC_GetValue(h);
    HAL_ADC_Stop(h);
    return DZ_OK;
#else
    (void)id; (void)raw; return DZ_ENODEV;
#endif
}
dz_err_t pal_adc_info(pal_id_t id, pal_adc_info_t *info)
{
#if BOARD_ADC_COUNT > 0
    if (id >= BOARD_ADC_COUNT) return DZ_ENODEV;
    if (info == 0) return DZ_EINVAL;
    *info = g_cm_adc[id].info;
    return DZ_OK;
#else
    (void)id; (void)info; return DZ_ENODEV;
#endif
}
