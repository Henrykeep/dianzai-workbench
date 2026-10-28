/**
 * @file port_stm32f4.h
 * @brief STM32F4 + HAL 移植层的内部类型。只允许 ports/stm32f4-hal 与生成的 board_gen.c 包含。
 *        应用层、驱动层、算法层包含本文件会被 tools/check_deps.py 拦截。
 */
#ifndef PORT_STM32F4_H
#define PORT_STM32F4_H

#include "stm32f4xx_hal.h"
#include "pal.h"

typedef struct {
    GPIO_TypeDef *port; uint16_t pin;
    uint8_t out; uint32_t pull; uint8_t active_low; uint8_t init; uint8_t open_drain;
} p4_gpio_t;

typedef struct {
    TIM_TypeDef *tim; uint32_t channel;
    GPIO_TypeDef *port; uint16_t pin; uint8_t af;
    uint8_t apb; uint32_t freq_hz;
} p4_pwm_t;

typedef struct {
    TIM_TypeDef *tim;
    GPIO_TypeDef *port_a; uint16_t pin_a;
    GPIO_TypeDef *port_b; uint16_t pin_b;
    uint8_t af; uint8_t bits; uint8_t invert; uint8_t filter;
} p4_enc_t;

typedef struct {
    USART_TypeDef *inst;
    GPIO_TypeDef *tx_port; uint16_t tx_pin;
    GPIO_TypeDef *rx_port; uint16_t rx_pin;
    uint8_t af; uint32_t baud;
    DMA_Stream_TypeDef *rx_stream; uint32_t rx_channel; IRQn_Type rx_irq;
    DMA_Stream_TypeDef *tx_stream; uint32_t tx_channel; IRQn_Type tx_irq;
    IRQn_Type uart_irq;
    uint8_t *rx_buf; uint16_t rx_size;
    uint8_t *tx_buf; uint16_t tx_size;
} p4_uart_t;

typedef struct {
    TIM_TypeDef *tim; uint8_t apb; IRQn_Type irq; uint8_t prio;
} p4_timer_t;

typedef struct {
    ADC_TypeDef *inst; uint32_t channel;
    GPIO_TypeDef *port; uint16_t pin;
    pal_adc_info_t info;
} p4_adc_t;

/* 由 board_gen.c 提供 */
extern const p4_gpio_t  g_p4_gpio[];
extern const p4_pwm_t   g_p4_pwm[];
extern const p4_enc_t   g_p4_enc[];
extern const p4_uart_t  g_p4_uart[];
extern const p4_timer_t g_p4_timer[];
extern const p4_adc_t   g_p4_adc[];
extern const char *const g_board_name;
void board_gen_clock_enable(void);

/* 由移植层提供给 board_gen.c 的中断转发入口 */
void p4_uart_rx_dma_irq(unsigned idx);
void p4_uart_tx_dma_irq(unsigned idx);
void p4_uart_irq(unsigned idx);
void p4_timer_irq(unsigned idx);

/** 移植层内部诊断：pal_init 中初始化失败的资源位图与是否发生了 HSE→HSI 回退。供移植自检读取。 */
typedef struct {
    uint32_t fail_gpio, fail_pwm, fail_enc, fail_uart, fail_timer, fail_adc;
    uint8_t  hse_fallback;
} p4_diag_t;
const p4_diag_t *p4_diag(void);

#endif /* PORT_STM32F4_H */
