/**
 * @file port_cubemx.h
 * @brief STM32 CubeMX 移植层的内部类型。CubeMX 是唯一的配置来源：时钟、引脚、DMA、中断优先级全部在 .ioc 里配，
 *        CubeMX 生成的 MX_xxx_Init() 完成初始化；本移植层只“包装”CubeMX 生成的 HAL 句柄（htimX/huartX/hadcX），
 *        不再做任何外设配置，因此与具体 STM32 系列无关（F1/F4/G4/L4… 只要 HAL API 相同即可）。
 *
 * 只允许 ports/stm32-cubemx 与生成的 board_gen.c 包含（tools/check_deps.py 会拦截其它地方）。
 */
#ifndef PORT_CUBEMX_H
#define PORT_CUBEMX_H

#include "main.h"      /* CubeMX 生成；它会包含对应系列的 stm32xxxx_hal.h */
#include "pal.h"

typedef struct { GPIO_TypeDef *port; uint16_t pin; uint8_t active_low; } cm_gpio_t;
typedef struct { TIM_HandleTypeDef *h; uint32_t channel; } cm_pwm_t;
typedef struct { TIM_HandleTypeDef *h; uint8_t invert; } cm_enc_t;
typedef struct { UART_HandleTypeDef *h; uint8_t *rx_buf; uint16_t rx_size; uint8_t *tx_buf; uint16_t tx_size; } cm_uart_t;
typedef struct { TIM_HandleTypeDef *h; } cm_timer_t;
#ifdef HAL_ADC_MODULE_ENABLED
typedef struct { ADC_HandleTypeDef *h; uint32_t channel; pal_adc_info_t info;
                 TIM_HandleTypeDef *blk_tim; uint32_t blk_trig; } cm_adc_t;
/**< blk_tim 非空 = board.yaml adc.block：该定时器 TRGO（更新事件）触发 ADC 规则组，DMA（CubeMX 里给该 ADC 配的
 *   DMA，Normal、半字）搬进缓冲；blk_trig = ADC_EXTERNALTRIGCONV_Tn_TRGO（1.10.0） */
#else   /* CubeMX 工程没启用 ADC（hal_conf 里没有 HAL_ADC_MODULE_ENABLED）：只留占位类型 */
typedef struct { void *h; uint32_t channel; pal_adc_info_t info; void *blk_tim; uint32_t blk_trig; } cm_adc_t;
#endif

/* 由 board_gen.c 提供（gen_board.py 按 board.yaml 生成，句柄名遵循 CubeMX 命名：TIM3 -> htim3，USART1 -> huart1） */
#ifdef HAL_I2C_MODULE_ENABLED
typedef struct { I2C_HandleTypeDef *h; } cm_i2c_t;
#else
typedef struct { void *h; } cm_i2c_t;
#endif
#ifdef HAL_SPI_MODULE_ENABLED
typedef struct { SPI_HandleTypeDef *h; GPIO_TypeDef *cs_port; uint16_t cs_pin; } cm_spi_t;
#else
typedef struct { void *h; GPIO_TypeDef *cs_port; uint16_t cs_pin; } cm_spi_t;
#endif
/** DAC 通道（PAL 1.7.0）：CubeMX 的 hdac / hdac1 句柄 + DAC_CHANNEL_x + 换算信息 */
#ifdef HAL_DAC_MODULE_ENABLED
typedef struct { DAC_HandleTypeDef *h; uint32_t channel; pal_dac_info_t info; } cm_dac_t;
#else
typedef struct { void *h; uint32_t channel; pal_dac_info_t info; } cm_dac_t;
#endif
extern const cm_dac_t   g_cm_dac[];
extern const cm_gpio_t  g_cm_gpio[];
extern const cm_pwm_t   g_cm_pwm[];
extern const cm_enc_t   g_cm_enc[];
extern const cm_uart_t  g_cm_uart[];
extern const cm_timer_t g_cm_timer[];
extern const cm_adc_t   g_cm_adc[];
extern const cm_i2c_t   g_cm_i2c[];
extern const cm_spi_t   g_cm_spi[];
extern const char *const g_board_name;
void dz_cm_selfinit(void);   /* board_gen.c（timer.self_init）强定义，否则 pal_cubemx.c 的弱空函数 */

/* 诊断计数（调试器里看） */
typedef struct { uint32_t uart_err; uint32_t tim_cb_unknown; } cm_diag_t;
const cm_diag_t *cm_diag(void);

#endif
