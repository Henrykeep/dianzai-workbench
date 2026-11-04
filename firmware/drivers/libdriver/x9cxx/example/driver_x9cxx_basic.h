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
 * @file      driver_x9cxx_basic.h
 * @brief     driver x9cxx basic header file
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

#ifndef DRIVER_X9CXX_BASIC_H
#define DRIVER_X9CXX_BASIC_H

#include "driver_x9cxx_interface.h"

#ifdef __cplusplus
extern "C"{
#endif

/**
 * @defgroup x9cxx_example_driver x9cxx example driver function
 * @brief    x9cxx example driver modules
 * @ingroup  x9cxx_driver
 * @{
 */

/**
 * @brief     basic example init
 * @param[in] type chip type
 * @return    status code
 *            - 0 success
 *            - 1 init failed
 * @note      none
 */
uint8_t x9cxx_basic_init(x9cxx_type_t type);

/**
 * @brief  basic example deinit
 * @return status code
 *         - 0 success
 *         - 1 deinit failed
 * @note   none
 */
uint8_t x9cxx_basic_deinit(void);

/**
 * @brief     basic example reset to min
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 reset to min failed
 * @note      none
 */
uint8_t x9cxx_basic_reset_to_min(x9cxx_bool_t store_enable);

/**
 * @brief     basic example reset to max
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 reset to max failed
 * @note      none
 */
uint8_t x9cxx_basic_reset_to_max(x9cxx_bool_t store_enable);

/**
 * @brief     basic example increment
 * @param[in] step step counter
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 increment failed
 * @note      none
 */
uint8_t x9cxx_basic_increment(uint8_t step, x9cxx_bool_t store_enable);

/**
 * @brief     basic example decrement
 * @param[in] step step counter
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 decrement failed
 * @note      none
 */
uint8_t x9cxx_basic_decrement(uint8_t step, x9cxx_bool_t store_enable);

/**
 * @brief     basic example set absolute step
 * @param[in] step step counter
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 set absolute step failed
 * @note      none
 */
uint8_t x9cxx_basic_set_absolute_step(uint8_t step, x9cxx_bool_t store_enable);

/**
 * @brief     basic example set absolute resistor
 * @param[in] ohm resistor ohm
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 set absolute resistor failed
 * @note      none
 */
uint8_t x9cxx_basic_set_absolute_resistor(float ohm, x9cxx_bool_t store_enable);

/**
 * @brief      basic example get resistor
 * @param[out] *step pointer to a step buffer
 * @param[out] *ohm pointer to an ohm buffer
 * @return     status code
 *             - 0 success
 *             - 1 get resistor failed
 * @note       none
 */
uint8_t x9cxx_basic_get_resistor(uint8_t *step, float *ohm);

/**
 * @}
 */

#ifdef __cplusplus
}
#endif

#endif
