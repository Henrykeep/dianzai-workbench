/*
 * 【合成样例】按 TI SysConfig（MSPM0 SDK 2.x）生成的 ti_msp_dl_config.h 的结构与命名手写，
 * **不是 SysConfig 的真实输出，未上板测试**。用你的 .syscfg 重新生成后整体替换本目录两个文件。
 * 移植层只依赖下面这些按实例名派生的宏（命名约定见 docs/10-SysConfig工作流.md）。
 */
#ifndef ti_msp_dl_config_h
#define ti_msp_dl_config_h

#define CONFIG_MSPM0G350X
#define CONFIG_MSPM0G3507

#if defined(__ti_version__) || defined(__TI_COMPILER_VERSION__)
#define SYSCONFIG_WEAK __attribute__((weak))
#elif defined(__IAR_SYSTEMS_ICC__)
#define SYSCONFIG_WEAK __weak
#elif defined(__GNUC__)
#define SYSCONFIG_WEAK __attribute__((weak))
#endif

#include <ti/devices/msp/msp.h>
#include <ti/driverlib/driverlib.h>
#include <ti/driverlib/m0p/dl_core.h>

#ifdef __cplusplus
extern "C" {
#endif

#define POWER_STARTUP_DELAY                                                (16)
#define CPUCLK_FREQ                                                     32000000

/* PWM_TIMG0：电机 A/B，20 kHz 边沿对齐 */
#define PWM_TIMG0_INST                                                     TIMG0
#define PWM_TIMG0_INST_IRQHandler                               TIMG0_IRQHandler
#define PWM_TIMG0_INST_INT_IRQN                                 (TIMG0_INT_IRQn)
#define PWM_TIMG0_INST_CLK_FREQ                                         32000000
#define GPIO_PWM_TIMG0_C0_PORT                                             GPIOA
#define GPIO_PWM_TIMG0_C0_PIN                                     DL_GPIO_PIN_12
#define GPIO_PWM_TIMG0_C0_IOMUX                                  (IOMUX_PINCM34)
#define GPIO_PWM_TIMG0_C0_IOMUX_FUNC                 IOMUX_PINCM34_PF_TIMG0_CCP0
#define GPIO_PWM_TIMG0_C0_IDX                                DL_TIMER_CC_0_INDEX
#define GPIO_PWM_TIMG0_C1_PORT                                             GPIOA
#define GPIO_PWM_TIMG0_C1_PIN                                     DL_GPIO_PIN_13
#define GPIO_PWM_TIMG0_C1_IOMUX                                  (IOMUX_PINCM35)
#define GPIO_PWM_TIMG0_C1_IOMUX_FUNC                 IOMUX_PINCM35_PF_TIMG0_CCP1
#define GPIO_PWM_TIMG0_C1_IDX                                DL_TIMER_CC_1_INDEX

/* ENC_MOTOR_A：TIMG8 QEI 2 输入 */
#define ENC_MOTOR_A_INST                                                   TIMG8
#define ENC_MOTOR_A_INST_IRQHandler                             TIMG8_IRQHandler
#define ENC_MOTOR_A_INST_INT_IRQN                               (TIMG8_INT_IRQn)
#define GPIO_ENC_MOTOR_A_PHA_PORT                                          GPIOA
#define GPIO_ENC_MOTOR_A_PHA_PIN                                  DL_GPIO_PIN_29
#define GPIO_ENC_MOTOR_A_PHA_IOMUX                                (IOMUX_PINCM4)
#define GPIO_ENC_MOTOR_A_PHA_IOMUX_FUNC               IOMUX_PINCM4_PF_TIMG8_CCP0
#define GPIO_ENC_MOTOR_A_PHB_PORT                                          GPIOA
#define GPIO_ENC_MOTOR_A_PHB_PIN                                  DL_GPIO_PIN_30
#define GPIO_ENC_MOTOR_A_PHB_IOMUX                                (IOMUX_PINCM5)
#define GPIO_ENC_MOTOR_A_PHB_IOMUX_FUNC               IOMUX_PINCM5_PF_TIMG8_CCP1

/* TIMER_CTRL：TIMG7 周期中断，计数时钟 1 MHz（32 MHz / 32） */
#define TIMER_CTRL_INST                                                    TIMG7
#define TIMER_CTRL_INST_IRQHandler                              TIMG7_IRQHandler
#define TIMER_CTRL_INST_INT_IRQN                                (TIMG7_INT_IRQn)
#define TIMER_CTRL_INST_LOAD_VALUE                                         (999U)
#define TIMER_CTRL_INST_CLK_FREQ                                         1000000

/* UART_LINK：UART0 115200 8N1 */
#define UART_LINK_INST                                                     UART0
#define UART_LINK_INST_FREQUENCY                                        32000000
#define UART_LINK_INST_IRQHandler                               UART0_IRQHandler
#define UART_LINK_INST_INT_IRQN                                   UART0_INT_IRQn
#define GPIO_UART_LINK_RX_PORT                                             GPIOA
#define GPIO_UART_LINK_TX_PORT                                             GPIOA
#define GPIO_UART_LINK_RX_PIN                                     DL_GPIO_PIN_11
#define GPIO_UART_LINK_TX_PIN                                     DL_GPIO_PIN_10
#define GPIO_UART_LINK_IOMUX_RX                                  (IOMUX_PINCM22)
#define GPIO_UART_LINK_IOMUX_TX                                  (IOMUX_PINCM21)
#define GPIO_UART_LINK_IOMUX_RX_FUNC                  IOMUX_PINCM22_PF_UART0_RX
#define GPIO_UART_LINK_IOMUX_TX_FUNC                  IOMUX_PINCM21_PF_UART0_TX
#define UART_LINK_BAUD_RATE                                             (115200)
#define UART_LINK_IBRD_32_MHZ_115200_BAUD                                   (17)
#define UART_LINK_FBRD_32_MHZ_115200_BAUD                                   (23)

/* GPIO 组：每个逻辑 GPIO 一个组（GPIO_<名>），组内引脚名为 PIN */
#define GPIO_MOTOR_A_IN1_PORT                                              GPIOB
#define GPIO_MOTOR_A_IN1_PIN_PIN                                  DL_GPIO_PIN_13
#define GPIO_MOTOR_A_IN1_PIN_IOMUX                               (IOMUX_PINCM30)
#define GPIO_MOTOR_A_IN2_PORT                                              GPIOB
#define GPIO_MOTOR_A_IN2_PIN_PIN                                  DL_GPIO_PIN_14
#define GPIO_MOTOR_A_IN2_PIN_IOMUX                               (IOMUX_PINCM31)
#define GPIO_MOTOR_B_IN1_PORT                                              GPIOB
#define GPIO_MOTOR_B_IN1_PIN_PIN                                  DL_GPIO_PIN_15
#define GPIO_MOTOR_B_IN1_PIN_IOMUX                               (IOMUX_PINCM32)
#define GPIO_MOTOR_B_IN2_PORT                                              GPIOB
#define GPIO_MOTOR_B_IN2_PIN_PIN                                  DL_GPIO_PIN_16
#define GPIO_MOTOR_B_IN2_PIN_IOMUX                               (IOMUX_PINCM33)

/* ENC_MOTOR_B：GPIO 组，A/B 两脚双边沿中断（GPIOB 在 INT_GROUP1） */
#define ENC_MOTOR_B_PORT                                                   GPIOB
#define ENC_MOTOR_B_INT_IRQN                                     (GPIOB_INT_IRQn)
#define ENC_MOTOR_B_INT_IIDX                     (DL_INTERRUPT_GROUP1_IIDX_GPIOB)
#define ENC_MOTOR_B_A_PIN                                          DL_GPIO_PIN_6
#define ENC_MOTOR_B_A_IOMUX                                      (IOMUX_PINCM23)
#define ENC_MOTOR_B_B_PIN                                          DL_GPIO_PIN_7
#define ENC_MOTOR_B_B_IOMUX                                      (IOMUX_PINCM24)

void SYSCFG_DL_init(void);
void SYSCFG_DL_initPower(void);
void SYSCFG_DL_GPIO_init(void);
void SYSCFG_DL_SYSCTL_init(void);
void SYSCFG_DL_PWM_TIMG0_init(void);
void SYSCFG_DL_ENC_MOTOR_A_init(void);
void SYSCFG_DL_TIMER_CTRL_init(void);
void SYSCFG_DL_UART_LINK_init(void);

#ifdef __cplusplus
}
#endif
#endif
