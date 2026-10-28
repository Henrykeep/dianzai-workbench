/**
 * @file port_mspm0.h
 * @brief MSPM0 SysConfig + DriverLib 移植层的内部类型。SysConfig（.syscfg -> ti_msp_dl_config.{c,h}）是唯一配置来源：
 *        时钟、引脚复用、定时器/串口参数都在 SysConfig 里配，SYSCFG_DL_init() 完成初始化；本层只包装它生成的
 *        实例宏（PWM_<定时器>_INST、ENC_<名>_INST、UART_<名>_INST、TIMER_<名>_INST、GPIO_<名>_PORT/GPIO_<名>_<名>_PIN），只调 DriverLib。
 *
 * 只允许 ports/mspm0-driverlib 与生成的 board_gen.c 包含。
 */
#ifndef PORT_MSPM0_H
#define PORT_MSPM0_H

#include "ti_msp_dl_config.h"
#include "pal.h"

typedef struct { GPIO_Regs *port; uint32_t pin; uint8_t active_low; } m0_gpio_t;
typedef struct { GPTIMER_Regs *inst; DL_TIMER_CC_INDEX cc; uint32_t clk_hz; } m0_pwm_t;
/** inst 非空 = 硬件 QEI；inst 为空 = GPIO 双边沿中断软件解码（port/pin_a/pin_b） */
typedef struct { GPTIMER_Regs *inst; GPIO_Regs *port; uint32_t pin_a; uint32_t pin_b; uint8_t invert; } m0_enc_t;
typedef struct { UART_Regs *inst; IRQn_Type irq; uint8_t *rx_buf; uint16_t rx_size; uint8_t *tx_buf; uint16_t tx_size; } m0_uart_t;
typedef struct { GPTIMER_Regs *inst; IRQn_Type irq; uint32_t clk_hz; uint32_t max_load; } m0_timer_t;

/* 由 board_gen.c 提供 */
extern const m0_gpio_t  g_m0_gpio[];
extern const m0_pwm_t   g_m0_pwm[];
extern const m0_enc_t   g_m0_enc[];
extern const m0_uart_t  g_m0_uart[];
extern const m0_timer_t g_m0_timer[];
extern const char *const g_board_name;

/* 中断入口：board_gen.c 生成 <实例>_IRQHandler 并转到这里（SysConfig 的 IRQHandler 宏给出真实向量名） */
void dz_m0_uart_isr(unsigned idx);
void dz_m0_timer_isr(unsigned idx);
void dz_m0_gpio_enc_isr(void);

typedef struct { uint32_t uart_err; uint32_t enc_glitch; } m0_diag_t;
const m0_diag_t *m0_diag(void);

#endif
