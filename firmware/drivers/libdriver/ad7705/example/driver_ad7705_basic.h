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
 * @file      driver_ad7705_basic.h
 * @brief     driver ad7705 basic include file
 * @version   1.0.0
 * @author    Shifeng Li
 * @date      2025-12-30
 *
 * <h3>history</h3>
 * <table>
 * <tr><th>Date        <th>Version  <th>Author      <th>Description
 * <tr><td>2025/12/30  <td>1.0      <td>Shifeng Li  <td>first upload
 * </table>
 */

#ifndef DRIVER_AD7705_BASIC_H
#define DRIVER_AD7705_BASIC_H

#include "driver_ad7705_interface.h"

#ifdef __cplusplus
extern "C"{
#endif

/**
 * @defgroup ad7705_example_driver ad7705 example driver function
 * @brief    ad7705 example driver modules
 * @ingroup  ad7705_driver
 * @{
 */

/**
 * @brief ad7705 basic example default definition
 */
#define AD7705_BASIC_DEFAULT_REFERENCE_VOLTAGE                  2.5f                            /**< reference voltage 2.5v */
#define AD7705_BASIC_DEFAULT_GAIN                               AD7705_ADC_GAIN_1               /**< gain 1 */
#define AD7705_BASIC_DEFAULT_ADC_BUFFER                         AD7705_BOOL_FALSE               /**< disable adc buffer */
#define AD7705_BASIC_DEFAULT_FILTER_SYNCHRONIZE                 AD7705_BOOL_TRUE                /**< enable filter synchronize */
#define AD7705_BASIC_DEFAULT_MASTER_CLOCK_OUTPUT_DISABLE        AD7705_BOOL_FALSE               /**< enable */
#define AD7705_BASIC_DEFAULT_CLOCK_DIV2                         AD7705_BOOL_FALSE               /**< disable div2 */
#define AD7705_BASIC_DEFAULT_RATE                               AD7705_RATE_50HZ                /**< 50hz */
#define AD7705_BASIC_DEFAULT_ADC_POLAR                          AD7705_ADC_POLAR_BIPOLAR        /**< bipolar */

/**
 * @brief     basic example init
 * @param[in] channel input channel
 * @return    status code
 *            - 0 success
 *            - 1 init failed
 * @note      none
 */
uint8_t ad7705_basic_init(ad7705_channel_t channel);

/**
 * @brief  basic example deinit
 * @return status code
 *         - 0 success
 *         - 1 deinit failed
 * @note   none
 */
uint8_t ad7705_basic_deinit(void);

/**
 * @brief     basic example set channel
 * @param[in] channel input channel
 * @return    status code
 *            - 0 success
 *            - 1 set channel failed
 * @note      none
 */
uint8_t ad7705_basic_set_channel(ad7705_channel_t channel);

/**
 * @brief      basic example read adc
 * @param[out] *raw pointer to a raw temperature buffer
 * @param[out] *volt pointer to a converted voltage buffer
 * @return     status code
 *             - 0 success
 *             - 1 read failed
 * @note       none
 */
uint8_t ad7705_basic_read(uint16_t *raw, float *volt);

/**
 * @}
 */

#ifdef __cplusplus
}
#endif

#endif
