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
 * @file      driver_tlc5615_basic.c
 * @brief     driver tlc5615 basic source file
 * @version   1.0.0
 * @author    Shifeng Li
 * @date      2026-07-30
 *
 * <h3>history</h3>
 * <table>
 * <tr><th>Date        <th>Version  <th>Author      <th>Description
 * <tr><td>2026/07/30  <td>1.0      <td>Shifeng Li  <td>first upload
 * </table>
 */

#include "driver_tlc5615_basic.h"

static tlc5615_handle_t gs_handle;        /**< tlc5615 handle */

/**
 * @brief     basic example init
 * @param[in] voltage_v reference voltage
 * @return    status code
 *            - 0 success
 *            - 1 init failed
 * @note      none
 */
uint8_t tlc5615_basic_init(float voltage_v)
{
    uint8_t res;
    
    /* link interface function */
    DRIVER_TLC5615_LINK_INIT(&gs_handle, tlc5615_handle_t);
    DRIVER_TLC5615_LINK_SPI_INIT(&gs_handle, tlc5615_interface_spi_init);
    DRIVER_TLC5615_LINK_SPI_DEINIT(&gs_handle, tlc5615_interface_spi_deinit);
    DRIVER_TLC5615_LINK_SPI_WRITE_COMMAND(&gs_handle, tlc5615_interface_spi_write_cmd);
    DRIVER_TLC5615_LINK_DELAY_MS(&gs_handle, tlc5615_interface_delay_ms);
    DRIVER_TLC5615_LINK_DEBUG_PRINT(&gs_handle, tlc5615_interface_debug_print);
    
    /* tlc5615 initialization */
    res = tlc5615_init(&gs_handle);
    if (res != 0)
    {
        tlc5615_interface_debug_print("tlc5615: init failed.\n");
       
        return 1;
    }
    
    /* set reference voltage */
    res = tlc5615_set_reference_voltage(&gs_handle, voltage_v);
    if (res != 0)
    {
        tlc5615_interface_debug_print("tlc5615: set reference voltage failed.\n");
       
        return 1;
    }
    
    return 0;
}

/**
 * @brief     basic example write 
 * @param[in] volt input volt
 * @return    status code
 *            - 0 success
 *            - 1 write failed
 * @note      none
 */
uint8_t tlc5615_basic_write(float volt)
{
    uint16_t reg;
    
    /* convert to register */
    if (tlc5615_voltage_convert_to_register(&gs_handle, volt, &reg) != 0)
    {
        return 1;
    }
    
    /* write */
    if (tlc5615_write(&gs_handle, reg) != 0)
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
uint8_t tlc5615_basic_deinit(void)
{
    /* deinit */
    if (tlc5615_deinit(&gs_handle) != 0)
    {
        return 1;
    }
    
    return 0;
}
