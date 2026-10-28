/**
 * @file pal_stm32f4.c
 * @brief pal.h 在 STM32F4 + STM32Cube HAL 上的实现。
 *
 * 板级差异（引脚、定时器、DMA、波特率）全部来自生成的 board_gen.c 资源表，
 * 本文件对同系列的所有板卡通用。新增同系列板卡不需要改这里。
 *
 * 时钟：HSE(board.yaml clock.hse_hz) -> PLL -> 168 MHz；HSE 起振失败自动回退到 HSI 16 MHz
 *       （仍为 168 MHz，但 USB/精确波特率受影响），回退情况记录在 p4_diag()->hse_fallback。
 *       APB1 = 42 MHz（定时器 84 MHz），APB2 = 84 MHz（定时器 168 MHz）。
 */
#include <string.h>
#include "board_gen.h"
#include "port_stm32f4.h"
#include "dz_wrap.h"

/* ------------------------------------------------------------------ 状态 */
static bool s_inited;
static pal_reset_cause_t s_reset;
static p4_diag_t s_diag;

#if BOARD_PWM_COUNT > 0
static TIM_HandleTypeDef s_pwm_htim[BOARD_PWM_COUNT];
#endif
#if BOARD_ENCODER_COUNT > 0
static TIM_HandleTypeDef s_enc_htim[BOARD_ENCODER_COUNT];
static uint32_t s_enc_last_raw[BOARD_ENCODER_COUNT];
static int32_t  s_enc_acc[BOARD_ENCODER_COUNT];
#endif
#if BOARD_UART_COUNT > 0
static UART_HandleTypeDef s_uart[BOARD_UART_COUNT];
static DMA_HandleTypeDef  s_dma_rx[BOARD_UART_COUNT];
static DMA_HandleTypeDef  s_dma_tx[BOARD_UART_COUNT];
static volatile uint32_t  s_rx_halves[BOARD_UART_COUNT];  /* DMA 半/满中断次数 */
static uint32_t           s_rx_read[BOARD_UART_COUNT];    /* 已读出的总字节数 */
static uint32_t           s_rx_dropped[BOARD_UART_COUNT];
#endif
#if BOARD_TIMER_COUNT > 0
static TIM_HandleTypeDef s_tmr[BOARD_TIMER_COUNT];
static pal_timer_cb_t    s_tmr_cb[BOARD_TIMER_COUNT];
static void             *s_tmr_ctx[BOARD_TIMER_COUNT];
#endif
#if BOARD_ADC_COUNT > 0
static ADC_HandleTypeDef s_adc[BOARD_ADC_COUNT];
#endif

const p4_diag_t *p4_diag(void) { return &s_diag; }

/* ------------------------------------------------------------------ 工具 */
static uint32_t timer_clock_hz(uint8_t apb)
{
    RCC_ClkInitTypeDef clk; uint32_t lat;
    HAL_RCC_GetClockConfig(&clk, &lat);
    if (apb == 2) {
        uint32_t p = HAL_RCC_GetPCLK2Freq();
        return clk.APB2CLKDivider == RCC_HCLK_DIV1 ? p : 2u * p;
    }
    uint32_t p = HAL_RCC_GetPCLK1Freq();
    return clk.APB1CLKDivider == RCC_HCLK_DIV1 ? p : 2u * p;
}

static void gpio_af(GPIO_TypeDef *port, uint16_t pin, uint8_t af, uint32_t pull)
{
    GPIO_InitTypeDef g = {0};
    g.Pin = pin; g.Mode = GPIO_MODE_AF_PP; g.Pull = pull;
    g.Speed = GPIO_SPEED_FREQ_VERY_HIGH; g.Alternate = af;
    HAL_GPIO_Init(port, &g);
}

/* ------------------------------------------------------------------ 时钟 */
static dz_err_t clock_init(void)
{
    RCC_OscInitTypeDef osc = {0};
    RCC_ClkInitTypeDef clk = {0};
    __HAL_RCC_PWR_CLK_ENABLE();
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

    osc.OscillatorType = RCC_OSCILLATORTYPE_HSE;
    osc.HSEState = RCC_HSE_ON;
    osc.PLL.PLLState = RCC_PLL_ON;
    osc.PLL.PLLSource = RCC_PLLSOURCE_HSE;
    osc.PLL.PLLM = HSE_VALUE / 1000000u;   /* VCO 输入 1 MHz */
    osc.PLL.PLLN = 336;                    /* VCO 336 MHz */
    osc.PLL.PLLP = RCC_PLLP_DIV2;          /* SYSCLK 168 MHz */
    osc.PLL.PLLQ = 7;                      /* 48 MHz 给 USB/SDIO */
    if (HAL_RCC_OscConfig(&osc) != HAL_OK) {
        s_diag.hse_fallback = 1;
        osc.OscillatorType = RCC_OSCILLATORTYPE_HSI;
        osc.HSEState = RCC_HSE_OFF;
        osc.HSIState = RCC_HSI_ON;
        osc.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
        osc.PLL.PLLSource = RCC_PLLSOURCE_HSI;
        osc.PLL.PLLM = 16;
        if (HAL_RCC_OscConfig(&osc) != HAL_OK) return DZ_EIO;
    }
    clk.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    clk.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    clk.AHBCLKDivider = RCC_SYSCLK_DIV1;
    clk.APB1CLKDivider = RCC_HCLK_DIV4;
    clk.APB2CLKDivider = RCC_HCLK_DIV2;
    if (HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_5) != HAL_OK) return DZ_EIO;
    return DZ_OK;
}

static pal_reset_cause_t read_reset_cause(void)
{
    pal_reset_cause_t r = PAL_RESET_UNKNOWN;
    /* 上电时 POR 与 BOR 标志会同时置位，所以先判断 POR */
    if (__HAL_RCC_GET_FLAG(RCC_FLAG_PORRST))       r = PAL_RESET_POWER_ON;
    else if (__HAL_RCC_GET_FLAG(RCC_FLAG_BORRST))  r = PAL_RESET_BROWNOUT;
    else if (__HAL_RCC_GET_FLAG(RCC_FLAG_IWDGRST) || __HAL_RCC_GET_FLAG(RCC_FLAG_WWDGRST))
                                                   r = PAL_RESET_WATCHDOG;
    else if (__HAL_RCC_GET_FLAG(RCC_FLAG_SFTRST))  r = PAL_RESET_SOFTWARE;
    else if (__HAL_RCC_GET_FLAG(RCC_FLAG_PINRST))  r = PAL_RESET_PIN;
    __HAL_RCC_CLEAR_RESET_FLAGS();
    return r;
}

/* ------------------------------------------------------------------ 初始化 */
static dz_err_t init_gpio(void)
{
    for (unsigned i = 0; i < BOARD_GPIO_COUNT; i++) {
        const p4_gpio_t *g = &g_p4_gpio[i];
        GPIO_InitTypeDef c = {0};
        c.Pin = g->pin; c.Pull = g->pull; c.Speed = GPIO_SPEED_FREQ_LOW;
        if (g->out) {
            /* 先写初始电平再切输出，避免上电毛刺（例如电机方向脚误动作） */
            HAL_GPIO_WritePin(g->port, g->pin, (g->init ^ g->active_low) ? GPIO_PIN_SET : GPIO_PIN_RESET);
            c.Mode = g->open_drain ? GPIO_MODE_OUTPUT_OD : GPIO_MODE_OUTPUT_PP;
        } else {
            c.Mode = GPIO_MODE_INPUT;
        }
        HAL_GPIO_Init(g->port, &c);
    }
    return DZ_OK;
}

#if BOARD_PWM_COUNT > 0
static dz_err_t init_pwm_one(unsigned i)
{
    const p4_pwm_t *p = &g_p4_pwm[i];
    TIM_HandleTypeDef *h = &s_pwm_htim[i];
    uint32_t tclk = timer_clock_hz(p->apb);
    uint32_t total = tclk / p->freq_hz;           /* (PSC+1)*(ARR+1) */
    if (total < 100u) return DZ_EINVAL;           /* 分辨率不足 1%，拒绝 */
    uint32_t psc = (total - 1u) / 65536u;         /* 让 ARR 尽量大以获得最高分辨率 */
    uint32_t arr = tclk / ((psc + 1u) * p->freq_hz) - 1u;

    /* 同一定时器的多个通道共享一个基准：若已有通道初始化过此定时器，只配通道 */
    bool shared = false;
    for (unsigned j = 0; j < i; j++) {
        if (g_p4_pwm[j].tim == p->tim) { *h = s_pwm_htim[j]; shared = true; break; }
    }
    if (!shared) {
        memset(h, 0, sizeof *h);
        h->Instance = p->tim;
        h->Init.Prescaler = psc;
        h->Init.CounterMode = TIM_COUNTERMODE_UP;
        h->Init.Period = arr;
        h->Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
        h->Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
        if (HAL_TIM_PWM_Init(h) != HAL_OK) return DZ_EIO;
    }
    TIM_OC_InitTypeDef oc = {0};
    oc.OCMode = TIM_OCMODE_PWM1; oc.Pulse = 0;
    oc.OCPolarity = TIM_OCPOLARITY_HIGH; oc.OCNPolarity = TIM_OCNPOLARITY_HIGH;
    oc.OCFastMode = TIM_OCFAST_DISABLE;
    oc.OCIdleState = TIM_OCIDLESTATE_RESET; oc.OCNIdleState = TIM_OCNIDLESTATE_RESET;
    if (HAL_TIM_PWM_ConfigChannel(h, &oc, p->channel) != HAL_OK) return DZ_EIO;
    gpio_af(p->port, p->pin, p->af, GPIO_NOPULL);
    if (HAL_TIM_PWM_Start(h, p->channel) != HAL_OK) return DZ_EIO; /* TIM1/8 的 MOE 由 HAL 打开 */
    return DZ_OK;
}
#endif

#if BOARD_ENCODER_COUNT > 0
static dz_err_t init_enc_one(unsigned i)
{
    const p4_enc_t *e = &g_p4_enc[i];
    TIM_HandleTypeDef *h = &s_enc_htim[i];
    memset(h, 0, sizeof *h);
    h->Instance = e->tim;
    h->Init.Prescaler = 0;
    h->Init.CounterMode = TIM_COUNTERMODE_UP;
    h->Init.Period = e->bits == 32 ? 0xFFFFFFFFu : 0xFFFFu;
    h->Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    TIM_Encoder_InitTypeDef c = {0};
    c.EncoderMode = TIM_ENCODERMODE_TI12;           /* 4 倍频 */
    c.IC1Polarity = TIM_ICPOLARITY_RISING; c.IC1Selection = TIM_ICSELECTION_DIRECTTI;
    c.IC1Prescaler = TIM_ICPSC_DIV1; c.IC1Filter = e->filter;
    c.IC2Polarity = TIM_ICPOLARITY_RISING; c.IC2Selection = TIM_ICSELECTION_DIRECTTI;
    c.IC2Prescaler = TIM_ICPSC_DIV1; c.IC2Filter = e->filter;
    gpio_af(e->port_a, e->pin_a, e->af, GPIO_PULLUP);
    gpio_af(e->port_b, e->pin_b, e->af, GPIO_PULLUP);
    if (HAL_TIM_Encoder_Init(h, &c) != HAL_OK) return DZ_EIO;
    if (HAL_TIM_Encoder_Start(h, TIM_CHANNEL_ALL) != HAL_OK) return DZ_EIO;
    s_enc_last_raw[i] = __HAL_TIM_GET_COUNTER(h);
    s_enc_acc[i] = 0;
    return DZ_OK;
}
#endif

#if BOARD_UART_COUNT > 0
static dz_err_t uart_start_rx(unsigned i)
{
    const p4_uart_t *u = &g_p4_uart[i];
    s_rx_halves[i] = 0;
    s_rx_read[i] = 0;
    if (HAL_UART_Receive_DMA(&s_uart[i], u->rx_buf, u->rx_size) != HAL_OK) return DZ_EIO;
    return DZ_OK;
}

static dz_err_t init_uart_one(unsigned i)
{
    const p4_uart_t *u = &g_p4_uart[i];
    UART_HandleTypeDef *h = &s_uart[i];
    memset(h, 0, sizeof *h);
    gpio_af(u->tx_port, u->tx_pin, u->af, GPIO_NOPULL);
    gpio_af(u->rx_port, u->rx_pin, u->af, GPIO_PULLUP);   /* 断线时 RX 保持空闲高电平 */
    h->Instance = u->inst;
    h->Init.BaudRate = u->baud;
    h->Init.WordLength = UART_WORDLENGTH_8B;
    h->Init.StopBits = UART_STOPBITS_1;
    h->Init.Parity = UART_PARITY_NONE;
    h->Init.Mode = UART_MODE_TX_RX;
    h->Init.HwFlowCtl = UART_HWCONTROL_NONE;
    h->Init.OverSampling = UART_OVERSAMPLING_16;
    if (HAL_UART_Init(h) != HAL_OK) return DZ_EIO;

    DMA_HandleTypeDef *r = &s_dma_rx[i], *t = &s_dma_tx[i];
    memset(r, 0, sizeof *r); memset(t, 0, sizeof *t);
    r->Instance = u->rx_stream; r->Init.Channel = u->rx_channel;
    r->Init.Direction = DMA_PERIPH_TO_MEMORY; r->Init.PeriphInc = DMA_PINC_DISABLE;
    r->Init.MemInc = DMA_MINC_ENABLE; r->Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
    r->Init.MemDataAlignment = DMA_MDATAALIGN_BYTE; r->Init.Mode = DMA_CIRCULAR;
    r->Init.Priority = DMA_PRIORITY_HIGH; r->Init.FIFOMode = DMA_FIFOMODE_DISABLE;
    if (HAL_DMA_Init(r) != HAL_OK) return DZ_EIO;
    __HAL_LINKDMA(h, hdmarx, *r);

    t->Instance = u->tx_stream; t->Init.Channel = u->tx_channel;
    t->Init.Direction = DMA_MEMORY_TO_PERIPH; t->Init.PeriphInc = DMA_PINC_DISABLE;
    t->Init.MemInc = DMA_MINC_ENABLE; t->Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
    t->Init.MemDataAlignment = DMA_MDATAALIGN_BYTE; t->Init.Mode = DMA_NORMAL;
    t->Init.Priority = DMA_PRIORITY_MEDIUM; t->Init.FIFOMode = DMA_FIFOMODE_DISABLE;
    if (HAL_DMA_Init(t) != HAL_OK) return DZ_EIO;
    __HAL_LINKDMA(h, hdmatx, *t);

    /* 通信中断优先级低于控制定时器（数值越大越低） */
    HAL_NVIC_SetPriority(u->rx_irq, 5, 0);   HAL_NVIC_EnableIRQ(u->rx_irq);
    HAL_NVIC_SetPriority(u->tx_irq, 5, 0);   HAL_NVIC_EnableIRQ(u->tx_irq);
    HAL_NVIC_SetPriority(u->uart_irq, 6, 0); HAL_NVIC_EnableIRQ(u->uart_irq);
    return uart_start_rx(i);
}
#endif

#if BOARD_ADC_COUNT > 0
static dz_err_t init_adc_one(unsigned i)
{
    const p4_adc_t *a = &g_p4_adc[i];
    GPIO_InitTypeDef g = {0};
    g.Pin = a->pin; g.Mode = GPIO_MODE_ANALOG; g.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(a->port, &g);
    /* 同一 ADC 实例只初始化一次 */
    for (unsigned j = 0; j < i; j++)
        if (g_p4_adc[j].inst == a->inst) { s_adc[i] = s_adc[j]; return DZ_OK; }
    ADC_HandleTypeDef *h = &s_adc[i];
    memset(h, 0, sizeof *h);
    h->Instance = a->inst;
    h->Init.ClockPrescaler = ADC_CLOCK_SYNC_PCLK_DIV4;   /* 84/4 = 21 MHz，低于 36 MHz 上限 */
    h->Init.Resolution = ADC_RESOLUTION_12B;
    h->Init.ScanConvMode = DISABLE;
    h->Init.ContinuousConvMode = DISABLE;
    h->Init.DiscontinuousConvMode = DISABLE;
    h->Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_NONE;
    h->Init.ExternalTrigConv = ADC_SOFTWARE_START;
    h->Init.DataAlign = ADC_DATAALIGN_RIGHT;
    h->Init.NbrOfConversion = 1;
    h->Init.EOCSelection = ADC_EOC_SINGLE_CONV;
    if (HAL_ADC_Init(h) != HAL_OK) return DZ_EIO;
    return DZ_OK;
}
#endif

/* ---------------------------------------------------------- I2C / SPI（阻塞式）
 * I2C：HAL_I2C_Mem_Read/Write，超时 PAL_I2C_TIMEOUT_MS。同一实例只初始化一次。
 * SPI：HAL_SPI_TransmitReceive + 软件片选（CS 推挽输出，空闲高）。共用总线的多个条目若 mode/速率不同，
 *      传输前按需重新 HAL_SPI_Init。中断里不要调用（阻塞）。 */
#if BOARD_I2C_COUNT > 0
static uint32_t s_fail_i2c;   /* 初始化失败位图（不放进 p4_diag_t，免得改动已发布的结构体） */
static I2C_HandleTypeDef s_i2c[BOARD_I2C_COUNT];
static I2C_HandleTypeDef *s_i2c_h[BOARD_I2C_COUNT];
static dz_err_t init_i2c_one(unsigned i)
{
    const p4_i2c_t *c = &g_p4_i2c[i];
    for (unsigned j = 0; j < i; j++)
        if (g_p4_i2c[j].inst == c->inst) { s_i2c_h[i] = s_i2c_h[j]; return DZ_OK; }
    GPIO_InitTypeDef g = {0};
    g.Mode = GPIO_MODE_AF_OD; g.Pull = GPIO_NOPULL; g.Speed = GPIO_SPEED_FREQ_HIGH; g.Alternate = c->af;
    g.Pin = c->scl_pin; HAL_GPIO_Init(c->scl_port, &g);
    g.Pin = c->sda_pin; HAL_GPIO_Init(c->sda_port, &g);
    I2C_HandleTypeDef *h = &s_i2c[i];
    memset(h, 0, sizeof *h);
    h->Instance = c->inst;
    h->Init.ClockSpeed = c->speed_hz;
    h->Init.DutyCycle = I2C_DUTYCYCLE_2;
    h->Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
    h->Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
    h->Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
    h->Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;
    s_i2c_h[i] = h;
    return HAL_I2C_Init(h) == HAL_OK ? DZ_OK : DZ_EIO;
}
static dz_err_t hal_rc(HAL_StatusTypeDef r) { return r == HAL_OK ? DZ_OK : r == HAL_TIMEOUT ? DZ_ETIMEOUT : r == HAL_BUSY ? DZ_EBUSY : DZ_EIO; }
#endif

dz_err_t pal_i2c_mem_read(pal_id_t id, uint8_t addr7, uint8_t reg, uint8_t *buf, uint16_t n)
{
#if BOARD_I2C_COUNT > 0
    if (id >= BOARD_I2C_COUNT) return DZ_ENODEV;
    if (!buf || !n || addr7 > 0x7Fu) return DZ_EINVAL;
    if (!s_inited) return DZ_ESTATE;
    if (s_fail_i2c & (1u << id)) return DZ_EIO;
    return hal_rc(HAL_I2C_Mem_Read(s_i2c_h[id], (uint16_t)(addr7 << 1), reg, I2C_MEMADD_SIZE_8BIT, buf, n, PAL_I2C_TIMEOUT_MS));
#else
    (void)id; (void)addr7; (void)reg; (void)buf; (void)n; return DZ_ENODEV;
#endif
}

dz_err_t pal_i2c_mem_write(pal_id_t id, uint8_t addr7, uint8_t reg, const uint8_t *buf, uint16_t n)
{
#if BOARD_I2C_COUNT > 0
    if (id >= BOARD_I2C_COUNT) return DZ_ENODEV;
    if ((!buf && n) || addr7 > 0x7Fu) return DZ_EINVAL;
    if (!s_inited) return DZ_ESTATE;
    if (s_fail_i2c & (1u << id)) return DZ_EIO;
    return hal_rc(HAL_I2C_Mem_Write(s_i2c_h[id], (uint16_t)(addr7 << 1), reg, I2C_MEMADD_SIZE_8BIT, (uint8_t *)buf, n, PAL_I2C_TIMEOUT_MS));
#else
    (void)id; (void)addr7; (void)reg; (void)buf; (void)n; return DZ_ENODEV;
#endif
}

#if BOARD_SPI_COUNT > 0
static uint32_t s_fail_spi;
static SPI_HandleTypeDef s_spi[BOARD_SPI_COUNT];
static SPI_HandleTypeDef *s_spi_h[BOARD_SPI_COUNT];
static int8_t s_spi_cfg_of[BOARD_SPI_COUNT];      /* 该句柄当前按哪个条目配置；-1 未配置 */

static uint32_t spi_prescaler(const p4_spi_t *c)
{
    static const uint32_t pre[8] = { SPI_BAUDRATEPRESCALER_2, SPI_BAUDRATEPRESCALER_4, SPI_BAUDRATEPRESCALER_8,
        SPI_BAUDRATEPRESCALER_16, SPI_BAUDRATEPRESCALER_32, SPI_BAUDRATEPRESCALER_64, SPI_BAUDRATEPRESCALER_128,
        SPI_BAUDRATEPRESCALER_256 };
    uint32_t pclk = c->apb == 2 ? HAL_RCC_GetPCLK2Freq() : HAL_RCC_GetPCLK1Freq();
    for (unsigned k = 0; k < 8; k++) if ((pclk >> (k + 1u)) <= c->hz) return pre[k];
    return SPI_BAUDRATEPRESCALER_256;            /* 不超过 hz 的最快分频；最慢 256 */
}
static dz_err_t spi_config(unsigned i)
{
    const p4_spi_t *c = &g_p4_spi[i];
    SPI_HandleTypeDef *h = s_spi_h[i];
    unsigned owner = (unsigned)(h - s_spi);
    if (s_spi_cfg_of[owner] >= 0) {
        const p4_spi_t *o = &g_p4_spi[s_spi_cfg_of[owner]];
        if (o->mode == c->mode && o->hz == c->hz) return DZ_OK;
        (void)HAL_SPI_DeInit(h);
    }
    h->Instance = c->inst;
    h->Init.Mode = SPI_MODE_MASTER;
    h->Init.Direction = SPI_DIRECTION_2LINES;
    h->Init.DataSize = SPI_DATASIZE_8BIT;
    h->Init.CLKPolarity = (c->mode & 2u) ? SPI_POLARITY_HIGH : SPI_POLARITY_LOW;
    h->Init.CLKPhase = (c->mode & 1u) ? SPI_PHASE_2EDGE : SPI_PHASE_1EDGE;
    h->Init.NSS = SPI_NSS_SOFT;
    h->Init.BaudRatePrescaler = spi_prescaler(c);
    h->Init.FirstBit = SPI_FIRSTBIT_MSB;
    h->Init.TIMode = SPI_TIMODE_DISABLE;
    h->Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
    h->Init.CRCPolynomial = 7;
    if (HAL_SPI_Init(h) != HAL_OK) { s_spi_cfg_of[owner] = -1; return DZ_EIO; }
    s_spi_cfg_of[owner] = (int8_t)i;
    return DZ_OK;
}
static dz_err_t init_spi_one(unsigned i)
{
    const p4_spi_t *c = &g_p4_spi[i];
    GPIO_InitTypeDef g = {0};
    g.Mode = GPIO_MODE_OUTPUT_PP; g.Pull = GPIO_NOPULL; g.Speed = GPIO_SPEED_FREQ_HIGH; g.Pin = c->cs_pin;
    HAL_GPIO_WritePin(c->cs_port, c->cs_pin, GPIO_PIN_SET);
    HAL_GPIO_Init(c->cs_port, &g);
    s_spi_cfg_of[i] = -1;
    for (unsigned j = 0; j < i; j++)
        if (g_p4_spi[j].inst == c->inst) { s_spi_h[i] = s_spi_h[j]; return DZ_OK; }
    g.Mode = GPIO_MODE_AF_PP; g.Speed = GPIO_SPEED_FREQ_VERY_HIGH; g.Alternate = c->af;
    g.Pin = c->sck_pin; HAL_GPIO_Init(c->sck_port, &g);
    g.Pin = c->miso_pin; HAL_GPIO_Init(c->miso_port, &g);
    g.Pin = c->mosi_pin; HAL_GPIO_Init(c->mosi_port, &g);
    memset(&s_spi[i], 0, sizeof s_spi[i]);
    s_spi_h[i] = &s_spi[i];
    return spi_config(i);
}
#endif

dz_err_t pal_spi_xfer(pal_id_t id, const uint8_t *tx, uint8_t *rx, uint16_t n)
{
#if BOARD_SPI_COUNT > 0
    static uint8_t ff[64], sink[64];
    if (id >= BOARD_SPI_COUNT) return DZ_ENODEV;
    if (!n || n > sizeof ff) return DZ_EINVAL;
    if (!s_inited) return DZ_ESTATE;
    if (s_fail_spi & (1u << id)) return DZ_EIO;
    const p4_spi_t *c = &g_p4_spi[id];
    dz_err_t e = spi_config(id);
    if (e) return e;
    if (!tx) { memset(ff, 0xFF, n); tx = ff; }
    HAL_GPIO_WritePin(c->cs_port, c->cs_pin, GPIO_PIN_RESET);
    HAL_StatusTypeDef r = HAL_SPI_TransmitReceive(s_spi_h[id], (uint8_t *)tx, rx ? rx : sink, n, PAL_I2C_TIMEOUT_MS);
    HAL_GPIO_WritePin(c->cs_port, c->cs_pin, GPIO_PIN_SET);
    return r == HAL_OK ? DZ_OK : r == HAL_TIMEOUT ? DZ_ETIMEOUT : DZ_EIO;
#else
    (void)id; (void)tx; (void)rx; (void)n; return DZ_ENODEV;
#endif
}

#define TRY_EACH(count, fn, mask)                                   \
    for (unsigned i_ = 0; i_ < (count); i_++)                       \
        if (fn(i_) != DZ_OK) { (mask) |= (1u << i_); rc = DZ_EIO; }

dz_err_t pal_init(void)
{
    if (s_inited) return DZ_ESTATE;
    dz_err_t rc = DZ_OK;
    s_reset = read_reset_cause();
    HAL_Init();                                  /* SysTick 1 kHz，优先级见 hal_conf TICK_INT_PRIORITY */
    if (clock_init() != DZ_OK) return DZ_EIO;
    HAL_InitTick(TICK_INT_PRIORITY);             /* 时钟变了，重新配置 SysTick */
    /* DZ-REG-OK: CMSIS 内核寄存器，HAL 无打开 DWT/跟踪单元的接口 */
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;

    board_gen_clock_enable();
    init_gpio();
#if BOARD_PWM_COUNT > 0
    TRY_EACH(BOARD_PWM_COUNT, init_pwm_one, s_diag.fail_pwm);
#endif
#if BOARD_ENCODER_COUNT > 0
    TRY_EACH(BOARD_ENCODER_COUNT, init_enc_one, s_diag.fail_enc);
#endif
#if BOARD_UART_COUNT > 0
    TRY_EACH(BOARD_UART_COUNT, init_uart_one, s_diag.fail_uart);
#endif
#if BOARD_ADC_COUNT > 0
    TRY_EACH(BOARD_ADC_COUNT, init_adc_one, s_diag.fail_adc);
#endif
#if BOARD_I2C_COUNT > 0
    TRY_EACH(BOARD_I2C_COUNT, init_i2c_one, s_fail_i2c);
#endif
#if BOARD_SPI_COUNT > 0
    TRY_EACH(BOARD_SPI_COUNT, init_spi_one, s_fail_spi);
#endif
    s_inited = true;   /* 部分失败也标记已初始化：失败的资源会在使用时报错，其余照常可用 */
    return rc;
}

const char *pal_board_name(void) { return g_board_name; }
pal_reset_cause_t pal_reset_cause(void) { return s_reset; }

uint32_t pal_irq_save(void) { uint32_t p = __get_PRIMASK(); __disable_irq(); return p; }
void pal_irq_restore(uint32_t s) { if (!s) __enable_irq(); }

/* ------------------------------------------------------------------ 时基 */
void SysTick_Handler(void) { HAL_IncTick(); }

uint32_t pal_millis(void) { return HAL_GetTick(); }

uint32_t pal_micros(void)
{
    /* 毫秒计数 + SysTick 当前值插值。处理两种竞争：
     *  1) 读取过程中毫秒中断到来 —— 前后两次毫秒不一致则重读
     *  2) 在关中断上下文中调用，SysTick 已回绕但中断挂起 —— 检查 PENDSTSET 补 1 ms */
    /* DZ-REG-OK: HAL 只提供 1 ms 节拍，微秒时间必须读 SysTick 计数（CMSIS 内核寄存器） */
    uint32_t ms, val, load = SysTick->LOAD + 1u;
    uint32_t ms2;
    do {
        ms = HAL_GetTick();
        val = SysTick->VAL;              /* DZ-REG-OK: 同上，读 SysTick 当前计数 */
        ms2 = HAL_GetTick();
    } while (ms != ms2);
    /* DZ-REG-OK: 判断 SysTick 中断是否挂起，HAL 无对应接口 */
    if ((SCB->ICSR & SCB_ICSR_PENDSTSET_Msk) && val > (load / 2u)) ms++;
    return ms * 1000u + ((load - 1u - val) * 1000u) / load;
}

void pal_delay_us(uint32_t us)
{
    uint32_t t0 = pal_micros();
    while ((uint32_t)(pal_micros() - t0) < us) { }
}

void pal_delay_ms(uint32_t ms)
{
    while (ms--) pal_delay_us(1000u);
}

/* ------------------------------------------------------------------ GPIO */
dz_err_t pal_gpio_write(pal_id_t id, bool active)
{
    if (id >= BOARD_GPIO_COUNT) return DZ_ENODEV;
    const p4_gpio_t *g = &g_p4_gpio[id];
    if (!g->out) return DZ_EINVAL;
    HAL_GPIO_WritePin(g->port, g->pin, ((uint8_t)active ^ g->active_low) ? GPIO_PIN_SET : GPIO_PIN_RESET);
    return DZ_OK;
}

dz_err_t pal_gpio_read(pal_id_t id, bool *active)
{
    if (id >= BOARD_GPIO_COUNT) return DZ_ENODEV;
    if (active == 0) return DZ_EINVAL;
    const p4_gpio_t *g = &g_p4_gpio[id];
    bool hi = HAL_GPIO_ReadPin(g->port, g->pin) == GPIO_PIN_SET;
    *active = hi ^ (g->active_low != 0);
    return DZ_OK;
}

dz_err_t pal_gpio_toggle(pal_id_t id)
{
    if (id >= BOARD_GPIO_COUNT) return DZ_ENODEV;
    if (!g_p4_gpio[id].out) return DZ_EINVAL;
    HAL_GPIO_TogglePin(g_p4_gpio[id].port, g_p4_gpio[id].pin);
    return DZ_OK;
}

/* ------------------------------------------------------------------ PWM */
dz_err_t pal_pwm_set_duty(pal_id_t id, uint16_t duty)
{
#if BOARD_PWM_COUNT > 0
    if (id >= BOARD_PWM_COUNT) return DZ_ENODEV;
    if (duty > PAL_DUTY_MAX) return DZ_EINVAL;
    if (s_diag.fail_pwm & (1u << id)) return DZ_EIO;
    TIM_HandleTypeDef *h = &s_pwm_htim[id];
    uint32_t top = __HAL_TIM_GET_AUTORELOAD(h) + 1u;
    __HAL_TIM_SET_COMPARE(h, g_p4_pwm[id].channel, (uint32_t)(((uint64_t)top * duty) / PAL_DUTY_MAX));
    return DZ_OK;
#else
    (void)id; (void)duty; return DZ_ENODEV;
#endif
}

dz_err_t pal_pwm_set_pulse_us(pal_id_t id, uint32_t pulse_us)
{
#if BOARD_PWM_COUNT > 0
    if (id >= BOARD_PWM_COUNT) return DZ_ENODEV;
    if (s_diag.fail_pwm & (1u << id)) return DZ_EIO;
    TIM_HandleTypeDef *h = &s_pwm_htim[id];
    uint32_t tick_hz = timer_clock_hz(g_p4_pwm[id].apb) / (h->Init.Prescaler + 1u);
    uint64_t ccr = ((uint64_t)pulse_us * tick_hz) / 1000000u;
    if (ccr > (uint64_t)__HAL_TIM_GET_AUTORELOAD(h) + 1u) return DZ_EINVAL;
    __HAL_TIM_SET_COMPARE(h, g_p4_pwm[id].channel, (uint32_t)ccr);
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
    TIM_HandleTypeDef *h = &s_pwm_htim[id];
    *freq_hz = timer_clock_hz(g_p4_pwm[id].apb) / ((h->Init.Prescaler + 1u) * (__HAL_TIM_GET_AUTORELOAD(h) + 1u));
    return DZ_OK;
#else
    (void)id; (void)freq_hz; return DZ_ENODEV;
#endif
}

/* ------------------------------------------------------------------ 编码器 */
dz_err_t pal_enc_get_count(pal_id_t id, int32_t *count)
{
#if BOARD_ENCODER_COUNT > 0
    if (id >= BOARD_ENCODER_COUNT) return DZ_ENODEV;
    if (count == 0) return DZ_EINVAL;
    if (s_diag.fail_enc & (1u << id)) return DZ_EIO;
    uint32_t st = pal_irq_save();
    uint32_t raw = __HAL_TIM_GET_COUNTER(&s_enc_htim[id]);
    int32_t d = g_p4_enc[id].bits == 32 ? dz_wrap32_delta(raw, s_enc_last_raw[id])
                                        : dz_wrap16_delta((uint16_t)raw, (uint16_t)s_enc_last_raw[id]);
    s_enc_last_raw[id] = raw;
    s_enc_acc[id] = (int32_t)((uint32_t)s_enc_acc[id] + (uint32_t)(g_p4_enc[id].invert ? -d : d));
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
    s_enc_last_raw[id] = __HAL_TIM_GET_COUNTER(&s_enc_htim[id]);
    s_enc_acc[id] = 0;
    pal_irq_restore(st);
    return DZ_OK;
#else
    (void)id; return DZ_ENODEV;
#endif
}

/* ------------------------------------------------------------------ UART */
#if BOARD_UART_COUNT > 0
static int uart_index(UART_HandleTypeDef *h)
{
    for (unsigned i = 0; i < BOARD_UART_COUNT; i++) if (&s_uart[i] == h) return (int)i;
    return -1;
}
void HAL_UART_RxHalfCpltCallback(UART_HandleTypeDef *h) { int i = uart_index(h); if (i >= 0) s_rx_halves[i]++; }
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *h)     { int i = uart_index(h); if (i >= 0) s_rx_halves[i]++; }
void HAL_UART_ErrorCallback(UART_HandleTypeDef *h)
{
    /* 溢出/噪声/帧错误时 HAL 会中止 DMA 接收：重新启动，丢失的数据计入 dropped（数量未知，记 1） */
    int i = uart_index(h);
    if (i < 0) return;
    s_rx_dropped[i]++;
    HAL_UART_AbortReceive(h);
    uart_start_rx((unsigned)i);
}
void p4_uart_rx_dma_irq(unsigned i) { HAL_DMA_IRQHandler(&s_dma_rx[i]); }
void p4_uart_tx_dma_irq(unsigned i) { HAL_DMA_IRQHandler(&s_dma_tx[i]); }
void p4_uart_irq(unsigned i)        { HAL_UART_IRQHandler(&s_uart[i]); }
#endif

dz_err_t pal_uart_write(pal_id_t id, const uint8_t *buf, uint16_t len)
{
#if BOARD_UART_COUNT > 0
    if (id >= BOARD_UART_COUNT) return DZ_ENODEV;
    if (buf == 0 && len) return DZ_EINVAL;
    const p4_uart_t *u = &g_p4_uart[id];
    if (len > u->tx_size) return DZ_EINVAL;   /* 帧比缓冲还大，永远发不出去 */
    if (len == 0) return DZ_OK;
    uint32_t st = pal_irq_save();
    bool busy = s_uart[id].gState != HAL_UART_STATE_READY;
    if (busy) { pal_irq_restore(st); return DZ_EBUSY; }
    memcpy(u->tx_buf, buf, len);
    HAL_StatusTypeDef r = HAL_UART_Transmit_DMA(&s_uart[id], u->tx_buf, len);
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
    *idle = s_uart[id].gState == HAL_UART_STATE_READY;
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
    const p4_uart_t *u = &g_p4_uart[id];
    const uint32_t size = u->rx_size, half = size / 2u;

    /* 计算 DMA 已写入的总字节数：半缓冲事件数 × half + 当前半区内偏移。
     * 关中断期间若 DMA 恰好越过半区边界而中断还没执行，手动处理挂起标志。 */
    uint32_t st = pal_irq_save();
    DMA_HandleTypeDef *d = &s_dma_rx[id];
    if (__HAL_DMA_GET_FLAG(d, __HAL_DMA_GET_HT_FLAG_INDEX(d))) { __HAL_DMA_CLEAR_FLAG(d, __HAL_DMA_GET_HT_FLAG_INDEX(d)); s_rx_halves[id]++; }
    if (__HAL_DMA_GET_FLAG(d, __HAL_DMA_GET_TC_FLAG_INDEX(d))) { __HAL_DMA_CLEAR_FLAG(d, __HAL_DMA_GET_TC_FLAG_INDEX(d)); s_rx_halves[id]++; }
    uint32_t pos = size - __HAL_DMA_GET_COUNTER(d);
    uint32_t written = s_rx_halves[id] * half + (pos % half);
    pal_irq_restore(st);

    uint32_t unread = written - s_rx_read[id];
    if (unread > size) {                          /* 读得太慢，旧数据已被覆盖 */
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

/* ------------------------------------------------------------------ 周期定时器 */
dz_err_t pal_timer_start(pal_id_t id, uint32_t period_us, pal_timer_cb_t cb, void *ctx)
{
#if BOARD_TIMER_COUNT > 0
    if (id >= BOARD_TIMER_COUNT) return DZ_ENODEV;
    if (cb == 0 || period_us == 0 || period_us > 65536u) return DZ_EINVAL;
    const p4_timer_t *t = &g_p4_timer[id];
    pal_timer_stop(id);
    uint32_t tclk = timer_clock_hz(t->apb);
    if (tclk % 1000000u) return DZ_EINVAL;       /* 1 MHz 计数必须整除，保证周期精确 */
    TIM_HandleTypeDef *h = &s_tmr[id];
    memset(h, 0, sizeof *h);
    h->Instance = t->tim;
    h->Init.Prescaler = tclk / 1000000u - 1u;    /* 1 µs 一个计数 */
    h->Init.CounterMode = TIM_COUNTERMODE_UP;
    h->Init.Period = period_us - 1u;
    h->Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
    if (HAL_TIM_Base_Init(h) != HAL_OK) return DZ_EIO;
    s_tmr_cb[id] = cb;
    s_tmr_ctx[id] = ctx;
    __HAL_TIM_CLEAR_FLAG(h, TIM_FLAG_UPDATE);    /* Init 会产生一次更新事件，清掉以免立刻进中断 */
    HAL_NVIC_SetPriority(t->irq, t->prio, 0);
    HAL_NVIC_EnableIRQ(t->irq);
    if (HAL_TIM_Base_Start_IT(h) != HAL_OK) return DZ_EIO;
    return DZ_OK;
#else
    (void)id; (void)period_us; (void)cb; (void)ctx; return DZ_ENODEV;
#endif
}

dz_err_t pal_timer_stop(pal_id_t id)
{
#if BOARD_TIMER_COUNT > 0
    if (id >= BOARD_TIMER_COUNT) return DZ_ENODEV;
    if (s_tmr[id].Instance) {
        HAL_TIM_Base_Stop_IT(&s_tmr[id]);
        HAL_NVIC_DisableIRQ(g_p4_timer[id].irq);
    }
    s_tmr_cb[id] = 0;
    return DZ_OK;
#else
    (void)id; return DZ_ENODEV;
#endif
}

#if BOARD_TIMER_COUNT > 0
void p4_timer_irq(unsigned i)
{
    TIM_HandleTypeDef *h = &s_tmr[i];
    if (__HAL_TIM_GET_FLAG(h, TIM_FLAG_UPDATE) && __HAL_TIM_GET_IT_SOURCE(h, TIM_IT_UPDATE)) {
        __HAL_TIM_CLEAR_IT(h, TIM_IT_UPDATE);
        if (s_tmr_cb[i]) s_tmr_cb[i](s_tmr_ctx[i]);
    }
}
#endif

/* ------------------------------------------------------------------ ADC */
dz_err_t pal_adc_read(pal_id_t id, uint16_t *raw)
{
#if BOARD_ADC_COUNT > 0
    if (id >= BOARD_ADC_COUNT) return DZ_ENODEV;
    if (raw == 0) return DZ_EINVAL;
    if (s_diag.fail_adc & (1u << id)) return DZ_EIO;
    ADC_HandleTypeDef *h = &s_adc[id];
    ADC_ChannelConfTypeDef c = {0};
    c.Channel = g_p4_adc[id].channel; c.Rank = 1; c.SamplingTime = ADC_SAMPLETIME_84CYCLES;
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
    *info = g_p4_adc[id].info;
    return DZ_OK;
#else
    (void)id; (void)info; return DZ_ENODEV;
#endif
}
