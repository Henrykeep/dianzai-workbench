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
 * @file      driver_tlc5615.h
 * @brief     driver tlc5615 header file
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

#ifndef DRIVER_TLC5615_H
#define DRIVER_TLC5615_H

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @defgroup tlc5615_driver tlc5615 driver function
 * @brief    tlc5615 driver modules
 * @{
 */

/**
 * @addtogroup tlc5615_base_driver
 * @{
 */

/**
 * @brief tlc5615 handle structure definition
 */
typedef struct tlc5615_handle_s
{
    uint8_t (*spi_init)(void);                                   /**< point to a spi_init function address */
    uint8_t (*spi_deinit)(void);                                 /**< point to a spi_deinit function address */
    uint8_t (*spi_write_cmd)(uint8_t *buf, uint16_t len);        /**< point to a spi_write_cmd function address */
    void (*delay_ms)(uint32_t ms);                               /**< point to a delay_ms function address */
    void (*debug_print)(const char *const fmt, ...);             /**< point to a debug_print function address */
    uint8_t inited;                                              /**< inited flag */
    float reference_voltage;                                     /**< reference voltage */
} tlc5615_handle_t;

/**
 * @brief tlc5615 information structure definition
 */
typedef struct tlc5615_info_s
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
} tlc5615_info_t;

/**
 * @}
 */

/**
 * @defgroup tlc5615_link_driver tlc5615 link driver function
 * @brief    tlc5615 link driver modules
 * @ingroup  tlc5615_driver
 * @{
 */

/**
 * @brief     initialize tlc5615_handle_t structure
 * @param[in] HANDLE pointer to a tlc5615 handle structure
 * @param[in] STRUCTURE tlc5615_handle_t
 * @note      none
 */
#define DRIVER_TLC5615_LINK_INIT(HANDLE, STRUCTURE)               memset(HANDLE, 0, sizeof(STRUCTURE))

/**
 * @brief     link spi_init function
 * @param[in] HANDLE pointer to a tlc5615 handle structure
 * @param[in] FUC pointer to a spi_init function address
 * @note      none
 */
#define DRIVER_TLC5615_LINK_SPI_INIT(HANDLE, FUC)                (HANDLE)->spi_init = FUC

/**
 * @brief     link spi_deinit function
 * @param[in] HANDLE pointer to a tlc5615 handle structure
 * @param[in] FUC pointer to a spi_deinit function address
 * @note      none
 */
#define DRIVER_TLC5615_LINK_SPI_DEINIT(HANDLE, FUC)              (HANDLE)->spi_deinit = FUC

/**
 * @brief     link spi_write_cmd function
 * @param[in] HANDLE pointer to a tlc5615 handle structure
 * @param[in] FUC pointer to a spi_write_cmd function address
 * @note      none
 */
#define DRIVER_TLC5615_LINK_SPI_WRITE_COMMAND(HANDLE, FUC)       (HANDLE)->spi_write_cmd = FUC

/**
 * @brief     link delay_ms function
 * @param[in] HANDLE pointer to a tlc5615 handle structure
 * @param[in] FUC pointer to a delay_ms function address
 * @note      none
 */
#define DRIVER_TLC5615_LINK_DELAY_MS(HANDLE, FUC)                (HANDLE)->delay_ms = FUC

/**
 * @brief     link debug_print function
 * @param[in] HANDLE pointer to a tlc5615 handle structure
 * @param[in] FUC pointer to a debug_print function address
 * @note      none
 */
#define DRIVER_TLC5615_LINK_DEBUG_PRINT(HANDLE, FUC)             (HANDLE)->debug_print = FUC

/**
 * @}
 */

/**
 * @defgroup tlc5615_base_driver tlc5615 base driver function
 * @brief    tlc5615 base driver modules
 * @ingroup  tlc5615_driver
 * @{
 */

/**
 * @brief      get chip's information
 * @param[out] *info pointer to a tlc5615 info structure
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 * @note       none
 */
uint8_t tlc5615_info(tlc5615_info_t *info);

/**
 * @brief     set reference voltage
 * @param[in] *handle pointer to a tlc5615 handle structure
 * @param[in] voltage_v reference voltage
 * @return    status code
 *            - 0 success
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t tlc5615_set_reference_voltage(tlc5615_handle_t *handle, float voltage_v);

/**
 * @brief      get reference voltage
 * @param[in]  *handle pointer to a tlc5615 handle structure
 * @param[out] *voltage_v pointer to a reference voltage buffer
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t tlc5615_get_reference_voltage(tlc5615_handle_t *handle, float *voltage_v);

/**
 * @brief     initialize the chip
 * @param[in] *handle pointer to a tlc5615 handle structure
 * @return    status code
 *            - 0 success
 *            - 1 spi initialization failed
 *            - 2 handle is NULL
 *            - 3 linked functions is NULL
 * @note      none
 */
uint8_t tlc5615_init(tlc5615_handle_t *handle);

/**
 * @brief     close the chip
 * @param[in] *handle pointer to a tlc5615 handle structure
 * @return    status code
 *            - 0 success
 *            - 1 spi deinit failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t tlc5615_deinit(tlc5615_handle_t *handle);

/**
 * @brief     write dac raw
 * @param[in] *handle pointer to a tlc5615 handle structure
 * @param[in] reg raw data
 * @return    status code
 *            - 0 success
 *            - 1 write failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 *            - 4 reg > 1023
 * @note      none
 */
uint8_t tlc5615_write(tlc5615_handle_t *handle, uint16_t reg);

/**
 * @brief      convert the voltage to the register raw data
 * @param[in]  *handle pointer to a tlc5615 handle structure
 * @param[in]  volt input volt
 * @param[out] *reg pointer to a register raw buffer
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t tlc5615_voltage_convert_to_register(tlc5615_handle_t *handle, float volt, uint16_t *reg);

/**
 * @brief      convert the register raw data to voltage
 * @param[in]  *handle pointer to a tlc5615 handle structure
 * @param[in]  reg register raw data
 * @param[out] *volt pointer to a volt buffer
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t tlc5615_voltage_convert_to_data(tlc5615_handle_t *handle, uint16_t reg, float *volt);

/**
 * @}
 */

/**
 * @defgroup tlc5615_extern_driver tlc5615 extern driver function
 * @brief    tlc5615 extern driver modules
 * @ingroup  tlc5615_driver
 * @{
 */

/**
 * @brief     set the chip register
 * @param[in] *handle pointer to a tlc5615 handle structure
 * @param[in] *buf pointer to a data buffer
 * @param[in] len data length
 * @return    status code
 *            - 0 success
 *            - 1 write failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t tlc5615_set_reg(tlc5615_handle_t *handle, uint8_t *buf, uint16_t len);

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
