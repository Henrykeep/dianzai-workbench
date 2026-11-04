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
 * @file      driver_ad7705_basic.c
 * @brief     driver ad7705 basic source file
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

#include "driver_ad7705_basic.h"

static ad7705_handle_t gs_handle;        /**< ad7705 handle */

/**
 * @brief     basic example init
 * @param[in] channel input channel
 * @return    status code
 *            - 0 success
 *            - 1 init failed
 * @note      none
 */
uint8_t ad7705_basic_init(ad7705_channel_t channel)
{
    uint8_t res;
    
    /* link functions */
    DRIVER_AD7705_LINK_INIT(&gs_handle, ad7705_handle_t);
    DRIVER_AD7705_LINK_GPIO_RESET_INIT(&gs_handle, ad7705_interface_gpio_reset_init);
    DRIVER_AD7705_LINK_GPIO_RESET_DEINIT(&gs_handle, ad7705_interface_gpio_reset_deinit);
    DRIVER_AD7705_LINK_GPIO_RESET_WRITE(&gs_handle, ad7705_interface_gpio_reset_write);
    DRIVER_AD7705_LINK_SPI_INIT(&gs_handle, ad7705_interface_spi_init);
    DRIVER_AD7705_LINK_SPI_DEINIT(&gs_handle, ad7705_interface_spi_deinit);
    DRIVER_AD7705_LINK_SPI_READ(&gs_handle, ad7705_interface_spi_read);
    DRIVER_AD7705_LINK_SPI_WRITE(&gs_handle, ad7705_interface_spi_write);
    DRIVER_AD7705_LINK_DELAY_MS(&gs_handle, ad7705_interface_delay_ms);
    DRIVER_AD7705_LINK_DEBUG_PRINT(&gs_handle, ad7705_interface_debug_print);
    
    /* ad7705 init */
    res = ad7705_init(&gs_handle);
    if (res != 0)
    {
        ad7705_interface_debug_print("ad7705: init failed.\n");
       
        return 1;
    }
    
    /* power on */
    res = ad7705_power_on(&gs_handle);
    if (res != 0)
    {
        ad7705_interface_debug_print("ad7705: power on failed.\n");
        (void)ad7705_deinit(&gs_handle);
        
        return 1;
    }
    
    /* set default reference voltage */
    res = ad7705_set_reference_voltage(&gs_handle, AD7705_BASIC_DEFAULT_REFERENCE_VOLTAGE);
    if (res != 0)
    {
        ad7705_interface_debug_print("ad7705: reference voltage failed.\n");
        (void)ad7705_deinit(&gs_handle);
        
        return 1;
    }
    
    /* set channel */
    res = ad7705_set_channel(&gs_handle, channel);
    if (res != 0)
    {
        ad7705_interface_debug_print("ad7705: set channel failed.\n");
        (void)ad7705_deinit(&gs_handle);
        
        return 1;
    }
    
    /* set default adc gain */
    res = ad7705_set_adc_gain(&gs_handle, AD7705_BASIC_DEFAULT_GAIN);
    if (res != 0)
    {
        ad7705_interface_debug_print("ad7705: set adc gain failed.\n");
        (void)ad7705_deinit(&gs_handle);
        
        return 1;
    }
    
    /* set default adc buffer */
    res = ad7705_set_adc_buffer(&gs_handle, AD7705_BASIC_DEFAULT_ADC_BUFFER);
    if (res != 0)
    {
        ad7705_interface_debug_print("ad7705: set adc buffer failed.\n");
        (void)ad7705_deinit(&gs_handle);
        
        return 1;
    }
    
    /* set default filter synchronize */
    res = ad7705_set_filter_synchronize(&gs_handle, AD7705_BASIC_DEFAULT_FILTER_SYNCHRONIZE);
    if (res != 0)
    {
        ad7705_interface_debug_print("ad7705: set filter synchronize failed.\n");
        (void)ad7705_deinit(&gs_handle);
        
        return 1;
    }
    
    /* set default master clock output disable */
    res = ad7705_set_master_clock_output_disable(&gs_handle, AD7705_BASIC_DEFAULT_MASTER_CLOCK_OUTPUT_DISABLE);
    if (res != 0)
    {
        ad7705_interface_debug_print("ad7705: set master clock output disable failed.\n");
        (void)ad7705_deinit(&gs_handle);
        
        return 1;
    }
    
    /* set default clock div2 */
    res = ad7705_set_clock_div2(&gs_handle, AD7705_BASIC_DEFAULT_CLOCK_DIV2);
    if (res != 0)
    {
        ad7705_interface_debug_print("ad7705: set clock div2 failed.\n");
        (void)ad7705_deinit(&gs_handle);
        
        return 1;
    }
    
    /* set default rate */
    res = ad7705_set_rate(&gs_handle, AD7705_BASIC_DEFAULT_RATE);
    if (res != 0)
    {
        ad7705_interface_debug_print("ad7705: set rate failed.\n");
        (void)ad7705_deinit(&gs_handle);
        
        return 1;
    }
    
    /* set default adc polar */
    res = ad7705_set_adc_polar(&gs_handle, AD7705_BASIC_DEFAULT_ADC_POLAR);
    if (res != 0)
    {
        ad7705_interface_debug_print("ad7705: set adc polar failed.\n");
        (void)ad7705_deinit(&gs_handle);
        
        return 1;
    }
    
    /* run self calibration */
    res = ad7705_set_adc_mode(&gs_handle, AD7705_ADC_MODE_SELF_CALIBRATION);
    if (res != 0)
    {
        ad7705_interface_debug_print("ad7705: set adc mode failed.\n");
        (void)ad7705_deinit(&gs_handle);
        
        return 1;
    }
    
    /* wait for finishing */
    res = ad7705_operate_sync(&gs_handle);
    if (res != 0)
    {
        ad7705_interface_debug_print("ad7705: operate sync failed.\n");
        (void)ad7705_deinit(&gs_handle);
        
        return 1;
    }
    
    return 0;
}

/**
 * @brief     basic example set channel
 * @param[in] channel input channel
 * @return    status code
 *            - 0 success
 *            - 1 set channel failed
 * @note      none
 */
uint8_t ad7705_basic_set_channel(ad7705_channel_t channel)
{
    uint8_t res;
    
    /* set channel */
    res = ad7705_set_channel(&gs_handle, channel);
    if (res != 0)
    {
        return 1;
    }
    
    return 0;
}

/**
 * @brief  basic example deinit
 * @return status code
 *         - 0 success
 *         - 1 deinit failed
 * @note   none
 */
uint8_t ad7705_basic_deinit(void)
{
    /* close ad7705 */
    if (ad7705_deinit(&gs_handle) != 0)
    {
        return 1;
    }
    
    return 0;
}

/**
 * @brief      basic example read adc
 * @param[out] *raw pointer to a raw temperature buffer
 * @param[out] *volt pointer to a converted voltage buffer
 * @return     status code
 *             - 0 success
 *             - 1 read failed
 * @note       none
 */
uint8_t ad7705_basic_read(uint16_t *raw, float *volt)
{
    /* read data */
    if (ad7705_read(&gs_handle, raw, volt) != 0)
    {
        return 1;
    }
    
    return 0;
}
