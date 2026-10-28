/*
 * Copyright (c) 2023, Texas Instruments Incorporated - http://www.ti.com
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *
 * *  Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 *
 * *  Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * *  Neither the name of Texas Instruments Incorporated nor the names of
 *    its contributors may be used to endorse or promote products derived
 *    from this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
 * THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 * PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR
 * CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
 * EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
 * PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
 * OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
 * WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
 * OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
 * EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

/*
 *  ============ ti_msp_dl_config.h =============
 *  Configured MSPM0 DriverLib module declarations
 *
 *  DO NOT EDIT - This file is generated for the MSPM0G350X
 *  by the SysConfig tool.
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

/*
 *  ======== SYSCFG_DL_init ========
 *  Perform all required MSP DL initialization
 *
 *  This function should be called once at a point before any use of
 *  MSP DL.
 */


/* clang-format off */

#define POWER_STARTUP_DELAY                                                (16)


#define CPUCLK_FREQ                                                     32000000



/* Defines for PWM_TIMG0 */
#define PWM_TIMG0_INST                                                     TIMG0
#define PWM_TIMG0_INST_IRQHandler                               TIMG0_IRQHandler
#define PWM_TIMG0_INST_INT_IRQN                                 (TIMG0_INT_IRQn)
#define PWM_TIMG0_INST_CLK_FREQ                                         32000000
/* GPIO defines for channel 0 */
#define GPIO_PWM_TIMG0_C0_PORT                                             GPIOA
#define GPIO_PWM_TIMG0_C0_PIN                                     DL_GPIO_PIN_12
#define GPIO_PWM_TIMG0_C0_IOMUX                                  (IOMUX_PINCM34)
#define GPIO_PWM_TIMG0_C0_IOMUX_FUNC                 IOMUX_PINCM34_PF_TIMG0_CCP0
#define GPIO_PWM_TIMG0_C0_IDX                                DL_TIMER_CC_0_INDEX
/* GPIO defines for channel 1 */
#define GPIO_PWM_TIMG0_C1_PORT                                             GPIOA
#define GPIO_PWM_TIMG0_C1_PIN                                     DL_GPIO_PIN_13
#define GPIO_PWM_TIMG0_C1_IOMUX                                  (IOMUX_PINCM35)
#define GPIO_PWM_TIMG0_C1_IOMUX_FUNC                 IOMUX_PINCM35_PF_TIMG0_CCP1
#define GPIO_PWM_TIMG0_C1_IDX                                DL_TIMER_CC_1_INDEX




/* Defines for ENC_MOTOR_A */
#define ENC_MOTOR_A_INST                                                   TIMG8
#define ENC_MOTOR_A_INST_IRQHandler                             TIMG8_IRQHandler
#define ENC_MOTOR_A_INST_INT_IRQN                               (TIMG8_INT_IRQn)
/* Pin configuration defines for ENC_MOTOR_A PHA Pin */
#define GPIO_ENC_MOTOR_A_PHA_PORT                                          GPIOA
#define GPIO_ENC_MOTOR_A_PHA_PIN                                  DL_GPIO_PIN_29
#define GPIO_ENC_MOTOR_A_PHA_IOMUX                                (IOMUX_PINCM4)
#define GPIO_ENC_MOTOR_A_PHA_IOMUX_FUNC               IOMUX_PINCM4_PF_TIMG8_CCP0
/* Pin configuration defines for ENC_MOTOR_A PHB Pin */
#define GPIO_ENC_MOTOR_A_PHB_PORT                                          GPIOA
#define GPIO_ENC_MOTOR_A_PHB_PIN                                  DL_GPIO_PIN_30
#define GPIO_ENC_MOTOR_A_PHB_IOMUX                                (IOMUX_PINCM5)
#define GPIO_ENC_MOTOR_A_PHB_IOMUX_FUNC               IOMUX_PINCM5_PF_TIMG8_CCP1


/* Defines for TIMER_CTRL */
#define TIMER_CTRL_INST                                                  (TIMG7)
#define TIMER_CTRL_INST_IRQHandler                              TIMG7_IRQHandler
#define TIMER_CTRL_INST_INT_IRQN                                (TIMG7_INT_IRQn)
#define TIMER_CTRL_INST_LOAD_VALUE                                        (999U)




/* Defines for I2C_IMU */
#define I2C_IMU_INST                                                        I2C0
#define I2C_IMU_INST_IRQHandler                                  I2C0_IRQHandler
#define I2C_IMU_INST_INT_IRQN                                      I2C0_INT_IRQn
#define I2C_IMU_BUS_SPEED_HZ                                              400000
#define GPIO_I2C_IMU_SDA_PORT                                              GPIOA
#define GPIO_I2C_IMU_SDA_PIN                                       DL_GPIO_PIN_0
#define GPIO_I2C_IMU_IOMUX_SDA                                    (IOMUX_PINCM1)
#define GPIO_I2C_IMU_IOMUX_SDA_FUNC                     IOMUX_PINCM1_PF_I2C0_SDA
#define GPIO_I2C_IMU_SCL_PORT                                              GPIOA
#define GPIO_I2C_IMU_SCL_PIN                                       DL_GPIO_PIN_1
#define GPIO_I2C_IMU_IOMUX_SCL                                    (IOMUX_PINCM2)
#define GPIO_I2C_IMU_IOMUX_SCL_FUNC                     IOMUX_PINCM2_PF_I2C0_SCL


/* Defines for UART_LINK */
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
#define GPIO_UART_LINK_IOMUX_RX_FUNC                   IOMUX_PINCM22_PF_UART0_RX
#define GPIO_UART_LINK_IOMUX_TX_FUNC                   IOMUX_PINCM21_PF_UART0_TX
#define UART_LINK_BAUD_RATE                                             (115200)
#define UART_LINK_IBRD_32_MHZ_115200_BAUD                                   (17)
#define UART_LINK_FBRD_32_MHZ_115200_BAUD                                   (23)
/* Defines for UART_IMU */
#define UART_IMU_INST                                                      UART1
#define UART_IMU_INST_FREQUENCY                                         32000000
#define UART_IMU_INST_IRQHandler                                UART1_IRQHandler
#define UART_IMU_INST_INT_IRQN                                    UART1_INT_IRQn
#define GPIO_UART_IMU_RX_PORT                                              GPIOA
#define GPIO_UART_IMU_TX_PORT                                              GPIOA
#define GPIO_UART_IMU_RX_PIN                                       DL_GPIO_PIN_9
#define GPIO_UART_IMU_TX_PIN                                       DL_GPIO_PIN_8
#define GPIO_UART_IMU_IOMUX_RX                                   (IOMUX_PINCM20)
#define GPIO_UART_IMU_IOMUX_TX                                   (IOMUX_PINCM19)
#define GPIO_UART_IMU_IOMUX_RX_FUNC                    IOMUX_PINCM20_PF_UART1_RX
#define GPIO_UART_IMU_IOMUX_TX_FUNC                    IOMUX_PINCM19_PF_UART1_TX
#define UART_IMU_BAUD_RATE                                              (460800)
#define UART_IMU_IBRD_32_MHZ_460800_BAUD                                     (4)
#define UART_IMU_FBRD_32_MHZ_460800_BAUD                                    (22)




/* Defines for SPI_BUS1 */
#define SPI_BUS1_INST                                                      SPI1
#define SPI_BUS1_INST_IRQHandler                                SPI1_IRQHandler
#define SPI_BUS1_INST_INT_IRQN                                    SPI1_INT_IRQn
#define GPIO_SPI_BUS1_PICO_PORT                                           GPIOB
#define GPIO_SPI_BUS1_PICO_PIN                                   DL_GPIO_PIN_22
#define GPIO_SPI_BUS1_IOMUX_PICO                                (IOMUX_PINCM50)
#define GPIO_SPI_BUS1_IOMUX_PICO_FUNC                IOMUX_PINCM50_PF_SPI1_PICO
#define GPIO_SPI_BUS1_POCI_PORT                                           GPIOB
#define GPIO_SPI_BUS1_POCI_PIN                                   DL_GPIO_PIN_21
#define GPIO_SPI_BUS1_IOMUX_POCI                                (IOMUX_PINCM49)
#define GPIO_SPI_BUS1_IOMUX_POCI_FUNC                IOMUX_PINCM49_PF_SPI1_POCI
/* GPIO configuration for SPI_BUS1 */
#define GPIO_SPI_BUS1_SCLK_PORT                                           GPIOB
#define GPIO_SPI_BUS1_SCLK_PIN                                   DL_GPIO_PIN_23
#define GPIO_SPI_BUS1_IOMUX_SCLK                                (IOMUX_PINCM51)
#define GPIO_SPI_BUS1_IOMUX_SCLK_FUNC                IOMUX_PINCM51_PF_SPI1_SCLK



/* Port definition for Pin Group GPIO_MOTOR_A_IN1 */
#define GPIO_MOTOR_A_IN1_PORT                                            (GPIOB)

/* Defines for MOTOR_A_IN1: GPIOB.13 with pinCMx 30 on package pin 1 */
#define GPIO_MOTOR_A_IN1_MOTOR_A_IN1_PIN                        (DL_GPIO_PIN_13)
#define GPIO_MOTOR_A_IN1_MOTOR_A_IN1_IOMUX                       (IOMUX_PINCM30)
/* Port definition for Pin Group GPIO_MOTOR_A_IN2 */
#define GPIO_MOTOR_A_IN2_PORT                                            (GPIOB)

/* Defines for MOTOR_A_IN2: GPIOB.14 with pinCMx 31 on package pin 2 */
#define GPIO_MOTOR_A_IN2_MOTOR_A_IN2_PIN                        (DL_GPIO_PIN_14)
#define GPIO_MOTOR_A_IN2_MOTOR_A_IN2_IOMUX                       (IOMUX_PINCM31)
/* Port definition for Pin Group GPIO_MOTOR_B_IN1 */
#define GPIO_MOTOR_B_IN1_PORT                                            (GPIOB)

/* Defines for MOTOR_B_IN1: GPIOB.15 with pinCMx 32 on package pin 3 */
#define GPIO_MOTOR_B_IN1_MOTOR_B_IN1_PIN                        (DL_GPIO_PIN_15)
#define GPIO_MOTOR_B_IN1_MOTOR_B_IN1_IOMUX                       (IOMUX_PINCM32)
/* Port definition for Pin Group GPIO_MOTOR_B_IN2 */
#define GPIO_MOTOR_B_IN2_PORT                                            (GPIOB)

/* Defines for MOTOR_B_IN2: GPIOB.16 with pinCMx 33 on package pin 4 */
#define GPIO_MOTOR_B_IN2_MOTOR_B_IN2_PIN                        (DL_GPIO_PIN_16)
#define GPIO_MOTOR_B_IN2_MOTOR_B_IN2_IOMUX                       (IOMUX_PINCM33)
/* Port definition for Pin Group GPIO_CS_SPI1_DEV */
#define GPIO_CS_SPI1_DEV_PORT                                            (GPIOB)

/* Defines for CS: GPIOB.20 with pinCMx 48 on package pin 19 */
#define GPIO_CS_SPI1_DEV_CS_PIN                                 (DL_GPIO_PIN_20)
#define GPIO_CS_SPI1_DEV_CS_IOMUX                                (IOMUX_PINCM48)
/* Port definition for Pin Group ENC_MOTOR_B */
#define ENC_MOTOR_B_PORT                                                 (GPIOB)

/* Defines for A: GPIOB.6 with pinCMx 23 on package pin 58 */
// pins affected by this interrupt request:["A","B"]
#define ENC_MOTOR_B_INT_IRQN                                    (GPIOB_INT_IRQn)
#define ENC_MOTOR_B_INT_IIDX                    (DL_INTERRUPT_GROUP1_IIDX_GPIOB)
#define ENC_MOTOR_B_A_IIDX                                   (DL_GPIO_IIDX_DIO6)
#define ENC_MOTOR_B_A_PIN                                        (DL_GPIO_PIN_6)
#define ENC_MOTOR_B_A_IOMUX                                      (IOMUX_PINCM23)
/* Defines for B: GPIOB.7 with pinCMx 24 on package pin 59 */
#define ENC_MOTOR_B_B_IIDX                                   (DL_GPIO_IIDX_DIO7)
#define ENC_MOTOR_B_B_PIN                                        (DL_GPIO_PIN_7)
#define ENC_MOTOR_B_B_IOMUX                                      (IOMUX_PINCM24)


/* clang-format on */

void SYSCFG_DL_init(void);
void SYSCFG_DL_initPower(void);
void SYSCFG_DL_GPIO_init(void);
void SYSCFG_DL_SYSCTL_init(void);
void SYSCFG_DL_PWM_TIMG0_init(void);
void SYSCFG_DL_ENC_MOTOR_A_init(void);
void SYSCFG_DL_TIMER_CTRL_init(void);
void SYSCFG_DL_I2C_IMU_init(void);
void SYSCFG_DL_UART_LINK_init(void);
void SYSCFG_DL_UART_IMU_init(void);
void SYSCFG_DL_SPI_BUS1_init(void);


bool SYSCFG_DL_saveConfiguration(void);
bool SYSCFG_DL_restoreConfiguration(void);

#ifdef __cplusplus
}
#endif

#endif /* ti_msp_dl_config_h */
