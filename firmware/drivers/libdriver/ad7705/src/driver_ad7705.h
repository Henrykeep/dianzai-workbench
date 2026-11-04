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
 * @file      driver_ad7705.h
 * @brief     driver ad7705 header file
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

#ifndef DRIVER_AD7705_H
#define DRIVER_AD7705_H

#include <stdio.h>
#include <stdint.h>
#include <string.h>

#ifdef __cplusplus
extern "C"{
#endif

/**
 * @defgroup ad7705_driver ad7705 driver function
 * @brief    ad7705 driver modules
 * @{
 */

/**
 * @addtogroup ad7705_base_driver
 * @{
 */

/**
 * @brief ad7705 bool enumeration definition
 */
typedef enum
{
    AD7705_BOOL_FALSE = 0x00,        /**< disable */
    AD7705_BOOL_TRUE  = 0x01,        /**< enable */
} ad7705_bool_t;

/**
 * @brief ad7705 channel enumeration definition
 */
typedef enum
{
    AD7705_CHANNEL_AIN1_POSITIVE_AIN1_NEGATIVE = 0x00,        /**< ain1 positive - ain1 negative */
    AD7705_CHANNEL_AIN2_POSITIVE_AIN2_NEGATIVE = 0x01,        /**< ain2 positive - ain2 negative */
    AD7705_CHANNEL_AIN1_NEGATIVE_AIN1_NEGATIVE = 0x02,        /**< ain1 negative - ain1 negative */
    AD7705_CHANNEL_AIN1_NEGATIVE_AIN2_NEGATIVE = 0x03,        /**< ain1 negative - ain2 negative */
} ad7705_channel_t;

/**
 * @brief ad7705 adc mode enumeration definition
 */
typedef enum
{
    AD7705_ADC_MODE_NORMAL                        = 0x00,        /**< normal mode */
    AD7705_ADC_MODE_SELF_CALIBRATION              = 0x01,        /**< self calibration */
    AD7705_ADC_MODE_ZERO_SCALE_SYSTEM_CALIBRATION = 0x02,        /**< zero scale system calibration */
    AD7705_ADC_MODE_FULL_SCALE_SYSTEM_CALIBRATION = 0x03,        /**< full scale system calibration */
} ad7705_adc_mode_t;

/**
 * @brief ad7705 adc gain enumeration definition
 */
typedef enum
{
    AD7705_ADC_GAIN_1   = 0x00,        /**< 1x */
    AD7705_ADC_GAIN_2   = 0x01,        /**< 2x */
    AD7705_ADC_GAIN_4   = 0x02,        /**< 4x */
    AD7705_ADC_GAIN_8   = 0x03,        /**< 8x */
    AD7705_ADC_GAIN_16  = 0x04,        /**< 16x */
    AD7705_ADC_GAIN_32  = 0x05,        /**< 32x */
    AD7705_ADC_GAIN_64  = 0x06,        /**< 64x */
    AD7705_ADC_GAIN_128 = 0x07,        /**< 128x */
} ad7705_adc_gain_t;

/**
 * @brief ad7705 adc polar enumeration definition
 */
typedef enum
{
    AD7705_ADC_POLAR_BIPOLAR  = 0x00,        /**< bipolar operation */
    AD7705_ADC_POLAR_UNIPOLAR = 0x01,        /**< unipolar operation */
} ad7705_adc_polar_t;

/**
 * @brief ad7705 rate enumeration definition
 */
typedef enum
{
    AD7705_RATE_20HZ  = 0x00,        /**< 20hz */
    AD7705_RATE_25HZ  = 0x01,        /**< 25hz */
    AD7705_RATE_100HZ = 0x02,        /**< 100hz */
    AD7705_RATE_200HZ = 0x03,        /**< 200hz */
    AD7705_RATE_50HZ  = 0x04,        /**< 50hz */
    AD7705_RATE_60HZ  = 0x05,        /**< 60hz */
    AD7705_RATE_250HZ = 0x06,        /**< 250hz */
    AD7705_RATE_500HZ = 0x07,        /**< 500hz */
} ad7705_rate_t;

/**
 * @brief ad7705 handle structure definition
 */
typedef struct ad7705_handle_s
{
    uint8_t (*gpio_reset_init)(void);                                       /**< point to a gpio_reset_init function address */
    uint8_t (*gpio_reset_deinit)(void);                                     /**< point to a gpio_reset_deinit function address */
    uint8_t (*gpio_reset_write)(uint8_t level);                             /**< point to a gpio_reset_write function address */
    uint8_t (*spi_init)(void);                                              /**< point to a spi_init function address */
    uint8_t (*spi_deinit)(void);                                            /**< point to a spi_deinit function address */
    uint8_t (*spi_write)(uint8_t addr, uint8_t *buf, uint16_t len);         /**< point to a spi_write function address */
    uint8_t (*spi_read)(uint8_t addr, uint8_t *buf, uint16_t len);          /**< point to a spi_read function address */
    void (*delay_ms)(uint32_t ms);                                          /**< point to a delay_ms function address */
    void (*debug_print)(const char *const fmt, ...);                        /**< point to a debug_print function address */
    uint8_t inited;                                                         /**< inited flag */
    uint8_t channel;                                                        /**< channel */
    uint8_t standby;                                                        /**< standby */
    float reference_voltage;                                                /**< reference voltage */
} ad7705_handle_t;

/**
 * @brief ad7705 information structure definition
 */
typedef struct ad7705_info_s
{
    char chip_name[32];                /**< chip name */
    char manufacturer_name[32];        /**< manufacturer name */
    char interface[8];                 /**< chip interface name */
    float supply_voltage_min_v;        /**< chip min supply voltage */
    float supply_voltage_max_v;        /**< chip max supply voltage */
    float max_current_ma;              /**< chip max current */
    float temperature_min;             /**< chip min operating temperature */
    float temperature_max;             /**< chip max operating temperature */
    uint32_t driver_version;           /**< driver version */
} ad7705_info_t;

/**
 * @}
 */

/**
 * @defgroup ad7705_link_driver ad7705 link driver function
 * @brief    ad7705 link driver modules
 * @ingroup  ad7705_driver
 * @{
 */

/**
 * @brief     initialize ad7705_handle_t structure
 * @param[in] HANDLE pointer to an ad7705 handle structure
 * @param[in] STRUCTURE ad7705_handle_t
 * @note      none
 */
#define DRIVER_AD7705_LINK_INIT(HANDLE, STRUCTURE)               memset(HANDLE, 0, sizeof(STRUCTURE))

/**
 * @brief     link spi_init function
 * @param[in] HANDLE pointer to an ad7705 handle structure
 * @param[in] FUC pointer to a spi_init function address
 * @note      none
 */
#define DRIVER_AD7705_LINK_SPI_INIT(HANDLE, FUC)                (HANDLE)->spi_init = FUC

/**
 * @brief     link spi_deinit function
 * @param[in] HANDLE pointer to an ad7705 handle structure
 * @param[in] FUC pointer to a spi_deinit function address
 * @note      none
 */
#define DRIVER_AD7705_LINK_SPI_DEINIT(HANDLE, FUC)              (HANDLE)->spi_deinit = FUC

/**
 * @brief     link spi_read function
 * @param[in] HANDLE pointer to an ad7705 handle structure
 * @param[in] FUC pointer to a spi_read function address
 * @note      none
 */
#define DRIVER_AD7705_LINK_SPI_READ(HANDLE, FUC)                (HANDLE)->spi_read = FUC

/**
 * @brief     link spi_write function
 * @param[in] HANDLE pointer to an ad7705 handle structure
 * @param[in] FUC pointer to a spi_write function address
 * @note      none
 */
#define DRIVER_AD7705_LINK_SPI_WRITE(HANDLE, FUC)               (HANDLE)->spi_write = FUC

/**
 * @brief     link gpio_reset_init function
 * @param[in] HANDLE pointer to an ad7705 handle structure
 * @param[in] FUC pointer to a gpio_reset_init function address
 * @note      none
 */
#define DRIVER_AD7705_LINK_GPIO_RESET_INIT(HANDLE, FUC)         (HANDLE)->gpio_reset_init = FUC

/**
 * @brief     link gpio_reset_deinit function
 * @param[in] HANDLE pointer to an ad7705 handle structure
 * @param[in] FUC pointer to a gpio_reset_deinit function address
 * @note      none
 */
#define DRIVER_AD7705_LINK_GPIO_RESET_DEINIT(HANDLE, FUC)       (HANDLE)->gpio_reset_deinit = FUC

/**
 * @brief     link gpio_reset_write function
 * @param[in] HANDLE pointer to an ad7705 handle structure
 * @param[in] FUC pointer to a gpio_reset_write function address
 * @note      none
 */
#define DRIVER_AD7705_LINK_GPIO_RESET_WRITE(HANDLE, FUC)        (HANDLE)->gpio_reset_write = FUC

/**
 * @brief     link delay_ms function
 * @param[in] HANDLE pointer to an ad7705 handle structure
 * @param[in] FUC pointer to a delay_ms function address
 * @note      none
 */
#define DRIVER_AD7705_LINK_DELAY_MS(HANDLE, FUC)                (HANDLE)->delay_ms = FUC

/**
 * @brief     link debug_print function
 * @param[in] HANDLE pointer to an ad7705 handle structure
 * @param[in] FUC pointer to a debug_print function address
 * @note      none
 */
#define DRIVER_AD7705_LINK_DEBUG_PRINT(HANDLE, FUC)             (HANDLE)->debug_print = FUC

/**
 * @}
 */

/**
 * @defgroup ad7705_base_driver ad7705 base driver function
 * @brief    ad7705 base driver modules
 * @ingroup  ad7705_driver
 * @{
 */

/**
 * @brief      get chip's information
 * @param[out] *info pointer to an ad7705 info structure
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 * @note       none
 */
uint8_t ad7705_info(ad7705_info_t *info);

/**
 * @brief     initialize the chip
 * @param[in] *handle pointer to an ad7705 handle structure
 * @return    status code
 *            - 0 success
 *            - 1 spi or gpio initialization failed
 *            - 2 handle is NULL
 *            - 3 linked functions is NULL
 *            - 4 chip reset failed
 *            - 5 power on failed
 * @note      none
 */
uint8_t ad7705_init(ad7705_handle_t *handle);

/**
 * @brief     close the chip
 * @param[in] *handle pointer to an ad7705 handle structure
 * @return    status code
 *            - 0 success
 *            - 1 deinit failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 *            - 4 power down failed
 * @note      none
 */
uint8_t ad7705_deinit(ad7705_handle_t *handle);

/**
 * @brief     set reference voltage
 * @param[in] *handle pointer to an ad7705 handle structure
 * @param[in] voltage reference voltage
 * @return    status code
 *            - 0 success
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t ad7705_set_reference_voltage(ad7705_handle_t *handle, float voltage);

/**
 * @brief      get reference voltage
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *voltage pointer to a reference voltage buffer
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_reference_voltage(ad7705_handle_t *handle, float *voltage);

/**
 * @brief     set channel
 * @param[in] *handle pointer to an ad7705 handle structure
 * @param[in] channel input channel
 * @return    status code
 *            - 0 success
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t ad7705_set_channel(ad7705_handle_t *handle, ad7705_channel_t channel);

/**
 * @brief      get channel
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *channel pointer to an input channel buffer
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_channel(ad7705_handle_t *handle, ad7705_channel_t *channel);

/**
 * @brief      read adc
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *raw pointer to a raw data buffer
 * @param[out] *volt pointer to a converted voltage buffer
 * @return     status code
 *             - 0 success
 *             - 1 read failed
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 *             - 4 read timeout
 * @note       none
 */
uint8_t ad7705_read(ad7705_handle_t *handle, uint16_t *raw, float *volt);

/**
 * @brief      get data ready
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *enable pointer to a bool value buffer
 * @return     status code
 *             - 0 success
 *             - 1 get data ready failed
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_data_ready(ad7705_handle_t *handle, ad7705_bool_t *enable);

/**
 * @brief     power on
 * @param[in] *handle pointer to an ad7705 handle structure
 * @return    status code
 *            - 0 success
 *            - 1 power on failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t ad7705_power_on(ad7705_handle_t *handle);

/**
 * @brief     power down
 * @param[in] *handle pointer to an ad7705 handle structure
 * @return    status code
 *            - 0 success
 *            - 1 power down failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t ad7705_power_down(ad7705_handle_t *handle);

/**
 * @brief     set adc mode
 * @param[in] *handle pointer to an ad7705 handle structure
 * @param[in] mode adc mode
 * @return    status code
 *            - 0 success
 *            - 1 set adc mode failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t ad7705_set_adc_mode(ad7705_handle_t *handle, ad7705_adc_mode_t mode);

/**
 * @brief      get adc mode
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *mode pointer to an adc mode buffer
 * @return     status code
 *             - 0 success
 *             - 1 get adc mode failed
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_adc_mode(ad7705_handle_t *handle, ad7705_adc_mode_t *mode);

/**
 * @brief     set adc gain
 * @param[in] *handle pointer to an ad7705 handle structure
 * @param[in] gain adc gain
 * @return    status code
 *            - 0 success
 *            - 1 set adc gain failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t ad7705_set_adc_gain(ad7705_handle_t *handle, ad7705_adc_gain_t gain);

/**
 * @brief      get adc gain
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *gain pointer to an adc gain buffer
 * @return     status code
 *             - 0 success
 *             - 1 get adc gain failed
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_adc_gain(ad7705_handle_t *handle, ad7705_adc_gain_t *gain);

/**
 * @brief     set adc polar
 * @param[in] *handle pointer to an ad7705 handle structure
 * @param[in] polar adc polar
 * @return    status code
 *            - 0 success
 *            - 1 set adc polar failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t ad7705_set_adc_polar(ad7705_handle_t *handle, ad7705_adc_polar_t polar);

/**
 * @brief      get adc polar
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *polar pointer to an adc polar buffer
 * @return     status code
 *             - 0 success
 *             - 1 get adc polar failed
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_adc_polar(ad7705_handle_t *handle, ad7705_adc_polar_t *polar);

/**
 * @brief     enable or disable adc buffer
 * @param[in] *handle pointer to an ad7705 handle structure
 * @param[in] enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 set adc buffer failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t ad7705_set_adc_buffer(ad7705_handle_t *handle, ad7705_bool_t enable);

/**
 * @brief      get adc buffer status
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *enable pointer to a bool value buffer
 * @return     status code
 *             - 0 success
 *             - 1 get adc buffer failed
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_adc_buffer(ad7705_handle_t *handle, ad7705_bool_t *enable);

/**
 * @brief     enable or disable filter synchronize
 * @param[in] *handle pointer to an ad7705 handle structure
 * @param[in] enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 set filter synchronize failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t ad7705_set_filter_synchronize(ad7705_handle_t *handle, ad7705_bool_t enable);

/**
 * @brief      get filter synchronize status
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *enable pointer to a bool value buffer
 * @return     status code
 *             - 0 success
 *             - 1 get filter synchronize failed
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_filter_synchronize(ad7705_handle_t *handle, ad7705_bool_t *enable);

/**
 * @brief     enable or disable master clock output disable
 * @param[in] *handle pointer to an ad7705 handle structure
 * @param[in] enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 set master clock output disable failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t ad7705_set_master_clock_output_disable(ad7705_handle_t *handle, ad7705_bool_t enable);

/**
 * @brief      get master clock output disable status
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *enable pointer to a bool value buffer
 * @return     status code
 *             - 0 success
 *             - 1 get master clock output disable failed
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_master_clock_output_disable(ad7705_handle_t *handle, ad7705_bool_t *enable);

/**
 * @brief     enable or disable clock div2
 * @param[in] *handle pointer to an ad7705 handle structure
 * @param[in] enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 set clock div2 failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t ad7705_set_clock_div2(ad7705_handle_t *handle, ad7705_bool_t enable);

/**
 * @brief      get clock div2 status
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *enable pointer to a bool value buffer
 * @return     status code
 *             - 0 success
 *             - 1 get clock div2 failed
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_clock_div2(ad7705_handle_t *handle, ad7705_bool_t *enable);

/**
 * @brief     set rate
 * @param[in] *handle pointer to an ad7705 handle structure
 * @param[in] rate sample rate
 * @return    status code
 *            - 0 success
 *            - 1 set rate failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t ad7705_set_rate(ad7705_handle_t *handle, ad7705_rate_t rate);

/**
 * @brief      get rate
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *rate pointer to a sample rate buffer
 * @return     status code
 *             - 0 success
 *             - 1 get rate failed
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_rate(ad7705_handle_t *handle, ad7705_rate_t *rate);

/**
 * @brief      get data
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *data pointer to a data buffer
 * @return     status code
 *             - 0 success
 *             - 1 get data failed
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_data(ad7705_handle_t *handle, uint16_t *data);

/**
 * @brief     set test data
 * @param[in] *handle pointer to an ad7705 handle structure
 * @param[in] data test data
 * @return    status code
 *            - 0 success
 *            - 1 set test failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t ad7705_set_test(ad7705_handle_t *handle, uint8_t data);

/**
 * @brief      get test data
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *data pointer to a test data buffer
 * @return     status code
 *             - 0 success
 *             - 1 get test failed
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_test(ad7705_handle_t *handle, uint8_t *data);

/**
 * @brief     set zero scale calibration
 * @param[in] *handle pointer to an ad7705 handle structure
 * @param[in] calibration zero scale calibration
 * @return    status code
 *            - 0 success
 *            - 1 set zero scale calibration failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t ad7705_set_zero_scale_calibration(ad7705_handle_t *handle, uint32_t calibration);

/**
 * @brief      get zero scale calibration
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *calibration pointer to a zero scale calibration buffer
 * @return     status code
 *             - 0 success
 *             - 1 get zero scale calibration failed
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_zero_scale_calibration(ad7705_handle_t *handle, uint32_t *calibration);

/**
 * @brief     set full scale calibration
 * @param[in] *handle pointer to an ad7705 handle structure
 * @param[in] calibration full scale calibration
 * @return    status code
 *            - 0 success
 *            - 1 set full scale calibration failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t ad7705_set_full_scale_calibration(ad7705_handle_t *handle, uint32_t calibration);

/**
 * @brief      get full scale calibration
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *calibration pointer to a full scale calibration buffer
 * @return     status code
 *             - 0 success
 *             - 1 get full scale calibration failed
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_full_scale_calibration(ad7705_handle_t *handle, uint32_t *calibration);

/**
 * @brief     operate sync
 * @param[in] *handle pointer to an ad7705 handle structure
 * @return    status code
 *            - 0 success
 *            - 1 sync failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 *            - 4 sync timeout
 * @note      none
 */
uint8_t ad7705_operate_sync(ad7705_handle_t *handle);

/**
 * @}
 */

/**
 * @defgroup ad7705_extern_driver ad7705 extern driver function
 * @brief    ad7705 extern driver modules
 * @ingroup  ad7705_driver
 * @{
 */

/**
 * @brief     set the chip register
 * @param[in] *handle pointer to an ad7705 handle structure
 * @param[in] addr address
 * @param[in] *buf pointer to a data buffer
 * @param[in] len buffer length
 * @return    status code
 *            - 0 success
 *            - 1 write failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t ad7705_set_reg(ad7705_handle_t *handle, uint8_t addr, uint8_t *buf, uint16_t len);

/**
 * @brief      get the chip register
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[in]  addr address
 * @param[out] *buf pointer to a data buffer
 * @param[in]  len buffer length
 * @return     status code
 *             - 0 success
 *             - 1 read failed
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_reg(ad7705_handle_t *handle, uint8_t addr, uint8_t *buf, uint16_t len);

/**
 * @}
 */

/**
 * @}
 */

#ifdef __cplusplus
}
#endif

#endif
