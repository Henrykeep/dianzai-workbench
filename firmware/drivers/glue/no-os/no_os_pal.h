/**
 * @file no_os_pal.h
 * @brief 芯台通用胶水：ADI no-OS 平台层（no_os_spi/i2c/gpio/uart platform_ops + delay）→ pal_*（XinTai 自写，AGPL-3.0-or-later）。
 *
 * 用法：init_param 里 platform_ops 填 &pal_spi_ops / &pal_i2c_ops / &pal_gpio_ops / &pal_uart_ops，
 *       device_id（GPIO 用 number）填 board.yaml 生成的 pal id（RES_SPI_xxx / RES_I2C_xxx / RES_GPIO_xxx / RES_UART_xxx）。
 * 限制：一个片选窗口 ≤ 64 字节（pal_spi_xfer）；I2C 读只支持“先写 1 字节寄存器（不带 STOP）再读”这种 no-OS 常见写法。
 */
#ifndef NO_OS_PAL_H
#define NO_OS_PAL_H
#include "no_os_spi.h"
#include "no_os_i2c.h"
#include "no_os_gpio.h"
#include "no_os_uart.h"

extern const struct no_os_spi_platform_ops pal_spi_ops;
extern const struct no_os_i2c_platform_ops pal_i2c_ops;
extern const struct no_os_gpio_platform_ops pal_gpio_ops;
extern const struct no_os_uart_platform_ops pal_uart_ops;

#endif
