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
 * @file      driver_x9cxx_basic.c
 * @brief     driver x9cxx basic source file
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

#include "driver_x9cxx_basic.h"

static x9cxx_handle_t gs_handle;        /**< x9cxx handle */

/**
 * @brief     basic example init
 * @param[in] type chip type
 * @return    status code
 *            - 0 success
 *            - 1 init failed
 * @note      none
 */
uint8_t x9cxx_basic_init(x9cxx_type_t type)
{
    uint8_t res;
    
    /* link functions */
    DRIVER_X9CXX_LINK_INIT(&gs_handle, x9cxx_handle_t);
    DRIVER_X9CXX_LINK_CS_GPIO_INIT(&gs_handle, x9cxx_interface_cs_gpio_init);
    DRIVER_X9CXX_LINK_CS_GPIO_DEINIT(&gs_handle, x9cxx_interface_cs_gpio_deinit);
    DRIVER_X9CXX_LINK_CS_GPIO_WRITE(&gs_handle, x9cxx_interface_cs_gpio_write);
    DRIVER_X9CXX_LINK_UP_DOWN_GPIO_INIT(&gs_handle, x9cxx_interface_up_down_gpio_init);
    DRIVER_X9CXX_LINK_UP_DOWN_GPIO_DEINIT(&gs_handle, x9cxx_interface_up_down_gpio_deinit);
    DRIVER_X9CXX_LINK_UP_DOWN_GPIO_WRITE(&gs_handle, x9cxx_interface_up_down_gpio_write);
    DRIVER_X9CXX_LINK_INC_GPIO_INIT(&gs_handle, x9cxx_interface_inc_gpio_init);
    DRIVER_X9CXX_LINK_INC_GPIO_DEINIT(&gs_handle, x9cxx_interface_inc_gpio_deinit);
    DRIVER_X9CXX_LINK_INC_GPIO_WRITE(&gs_handle, x9cxx_interface_inc_gpio_write);
    DRIVER_X9CXX_LINK_DEBUG_PRINT(&gs_handle, x9cxx_interface_debug_print);
    DRIVER_X9CXX_LINK_DELAY_MS(&gs_handle, x9cxx_interface_delay_ms);
    DRIVER_X9CXX_LINK_DELAY_US(&gs_handle, x9cxx_interface_delay_us);
    
    /* set type */
    res = x9cxx_set_type(&gs_handle, type);
    if (res != 0)
    {
        x9cxx_interface_debug_print("x9cxx: set type failed.\n");
        
        return 1;
    }
    
    /* x9cxx init */
    res = x9cxx_init(&gs_handle);
    if (res != 0)
    {
        x9cxx_interface_debug_print("x9cxx: init failed.\n");
        
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
uint8_t x9cxx_basic_deinit(void)
{
    /* deinit x9cxx */
    if (x9cxx_deinit(&gs_handle) != 0)
    {
        return 1;
    }
    
    return 0;
}

/**
 * @brief     basic example reset to min
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 reset to min failed
 * @note      none
 */
uint8_t x9cxx_basic_reset_to_min(x9cxx_bool_t store_enable)
{
    uint8_t res;
    
    /* reset to min */
    res = x9cxx_reset_to_min(&gs_handle, store_enable);
    if (res != 0)
    {
        return 1;
    }
    
    return 0;
}

/**
 * @brief     basic example reset to max
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 reset to max failed
 * @note      none
 */
uint8_t x9cxx_basic_reset_to_max(x9cxx_bool_t store_enable)
{
    uint8_t res;
    
    /* reset to max */
    res = x9cxx_reset_to_max(&gs_handle, store_enable);
    if (res != 0)
    {
        return 1;
    }
    
    return 0;
}

/**
 * @brief     basic example increment
 * @param[in] step step counter
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 increment failed
 * @note      none
 */
uint8_t x9cxx_basic_increment(uint8_t step, x9cxx_bool_t store_enable)
{
    uint8_t res;
    
    /* increment */
    res = x9cxx_increment(&gs_handle, step, store_enable);
    if (res != 0)
    {
        return 1;
    }
    
    return 0;
}

/**
 * @brief     basic example decrement
 * @param[in] step step counter
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 decrement failed
 * @note      none
 */
uint8_t x9cxx_basic_decrement(uint8_t step, x9cxx_bool_t store_enable)
{
    uint8_t res;
    
    /* decrement */
    res = x9cxx_decrement(&gs_handle, step, store_enable);
    if (res != 0)
    {
        return 1;
    }
    
    return 0;
}

/**
 * @brief     basic example set absolute step
 * @param[in] step step counter
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 set absolute step failed
 * @note      none
 */
uint8_t x9cxx_basic_set_absolute_step(uint8_t step, x9cxx_bool_t store_enable)
{
    uint8_t res;
    
    /* set absolute step counter */
    res = x9cxx_set_absolute_step_counter(&gs_handle, step, store_enable);
    if (res != 0)
    {
        return 1;
    }
    
    return 0;
}

/**
 * @brief     basic example set absolute resistor
 * @param[in] ohm resistor ohm
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 set absolute resistor failed
 * @note      none
 */
uint8_t x9cxx_basic_set_absolute_resistor(float ohm, x9cxx_bool_t store_enable)
{
    uint8_t res;
    uint8_t step;
    
    /* convert to register */
    res = x9cxx_resistor_convert_to_register(&gs_handle, ohm, &step);
    if (res != 0)
    {
        return 1;
    }
    
    /* set absolute step counter */
    res = x9cxx_set_absolute_step_counter(&gs_handle, step, store_enable);
    if (res != 0)
    {
        return 1;
    }
    
    return 0;
}

/**
 * @brief      basic example get resistor
 * @param[out] *step pointer to a step buffer
 * @param[out] *ohm pointer to an ohm buffer
 * @return     status code
 *             - 0 success
 *             - 1 get resistor failed
 * @note       none
 */
uint8_t x9cxx_basic_get_resistor(uint8_t *step, float *ohm)
{
    uint8_t res;
    
    /* get step counter */
    res = x9cxx_get_step_counter(&gs_handle, step);
    if (res != 0)
    {
        return 1;
    }
    
    /* convert to data */
    res = x9cxx_resistor_convert_to_data(&gs_handle, *step, ohm);
    if (res != 0)
    {
        return 1;
    }
    
    return 0;
}
