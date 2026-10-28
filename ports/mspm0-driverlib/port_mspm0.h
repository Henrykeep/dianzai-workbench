/**
 * @file port_mspm0.h
 * @brief MSPM0 SysConfig + DriverLib 移植层的内部类型。SysConfig（.syscfg -> ti_msp_dl_config.{c,h}）是唯一配置来源：
 *        时钟、引脚复用、定时器/串口参数都在 SysConfig 里配，SYSCFG_DL_init() 完成初始化；本层只包装它生成的
 *        实例宏（PWM_<定时器>_INST、ENC_<名>_INST、UART_<名>_INST、TIMER_<名>_INST、I2C_<名>_INST、SPI_BUS<n>_INST、GPIO_<名>_PORT/GPIO_<名>_<名>_PIN），只调 DriverLib。
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
/** I2C 主机实例（速率、上拉、毛刺滤波都在 SysConfig） */
typedef struct { I2C_Regs *inst; } m0_i2c_t;
/** 一个 SPI 设备 = 总线实例 + 软件片选 GPIO（低有效；模式/速率在 SysConfig 的总线实例里，同总线设备共用） */
typedef struct { SPI_Regs *inst; GPIO_Regs *cs_port; uint32_t cs_pin; } m0_spi_t;

/* 由 board_gen.c 提供 */
extern const m0_gpio_t  g_m0_gpio[];
extern const m0_pwm_t   g_m0_pwm[];
extern const m0_enc_t   g_m0_enc[];
extern const m0_uart_t  g_m0_uart[];
extern const m0_timer_t g_m0_timer[];
extern const m0_i2c_t   g_m0_i2c[];
extern const m0_spi_t   g_m0_spi[];
extern const char *const g_board_name;

/* 中断入口：board_gen.c 生成 <实例>_IRQHandler 并转到这里（SysConfig 的 IRQHandler 宏给出真实向量名） */
void dz_m0_uart_isr(unsigned idx);
void dz_m0_timer_isr(unsigned idx);
void dz_m0_gpio_enc_isr(void);

typedef struct { uint32_t uart_err; uint32_t enc_glitch; uint32_t i2c_err; uint32_t i2c_timeout; uint32_t spi_timeout; } m0_diag_t;
const m0_diag_t *m0_diag(void);

#endif
