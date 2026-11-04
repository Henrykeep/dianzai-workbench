/**
 * Copyright (c) 2015 - present LibDriver All rights reserved
 * 
 * The MIT License (MIT)
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE. 
 *
 * @file      driver_x9cxx_interface.h
 * @brief     driver x9cxx interface header file
 * @version   1.0.0
 * @author    Shifeng Li
 * @date      2025-10-19
 *
 * <h3>history</h3>
 * <table>
 * <tr><th>Date        <th>Version  <th>Author      <th>Description
 * <tr><td>2025/10/19  <td>1.0      <td>Shifeng Li  <td>first upload
 * </table>
 */

#ifndef DRIVER_X9CXX_INTERFACE_H
#define DRIVER_X9CXX_INTERFACE_H

#include "driver_x9cxx.h"

#ifdef __cplusplus
extern "C"{
#endif

/**
 * @defgroup x9cxx_interface_driver x9cxx interface driver function
 * @brief    x9cxx interface driver modules
 * @ingroup  x9cxx_driver
 * @{
 */

/**
 * @brief  interface cs gpio init
 * @return status code
 *         - 0 success
 *         - 1 init failed
 * @note   none
 */
uint8_t x9cxx_interface_cs_gpio_init(void);

/**
 * @brief  interface cs gpio deinit
 * @return status code
 *         - 0 success
 *         - 1 deinit failed
 * @note   none
 */
uint8_t x9cxx_interface_cs_gpio_deinit(void);

/**
 * @brief     interface cs gpio write
 * @param[in] value written value
 * @return    status code
 *            - 0 success
 *            - 1 write failed
 * @note      none
 */
uint8_t x9cxx_interface_cs_gpio_write(uint8_t value);

/**
 * @brief  interface up down gpio init
 * @return status code
 *         - 0 success
 *         - 1 init failed
 * @note   none
 */
uint8_t x9cxx_interface_up_down_gpio_init(void);

/**
 * @brief  interface up down gpio deinit
 * @return status code
 *         - 0 success
 *         - 1 deinit failed
 * @note   none
 */
uint8_t x9cxx_interface_up_down_gpio_deinit(void);

/**
 * @brief     interface up down gpio write
 * @param[in] value written value
 * @return    status code
 *            - 0 success
 *            - 1 write failed
 * @note      none
 */
uint8_t x9cxx_interface_up_down_gpio_write(uint8_t value);

/**
 * @brief  interface inc gpio init
 * @return status code
 *         - 0 success
 *         - 1 init failed
 * @note   none
 */
uint8_t x9cxx_interface_inc_gpio_init(void);

/**
 * @brief  interface inc gpio deinit
 * @return status code
 *         - 0 success
 *         - 1 deinit failed
 * @note   none
 */
uint8_t x9cxx_interface_inc_gpio_deinit(void);

/**
 * @brief     interface inc gpio write
 * @param[in] value written value
 * @return    status code
 *            - 0 success
 *            - 1 write failed
 * @note      none
 */
uint8_t x9cxx_interface_inc_gpio_write(uint8_t value);

/**
 * @brief     interface delay ms
 * @param[in] ms time
 * @note      none
 */
void x9cxx_interface_delay_ms(uint32_t ms);

/**
 * @brief     interface delay us
 * @param[in] us time
 * @note      none
 */
void x9cxx_interface_delay_us(uint32_t us);

/**
 * @brief     interface print format data
 * @param[in] fmt format data
 * @note      none
 */
void x9cxx_interface_debug_print(const char *const fmt, ...);

/**
 * @}
 */

#ifdef __cplusplus
}
#endif

#endif
