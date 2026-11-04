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
 * @file      driver_x9cxx.h
 * @brief     driver x9cxx header file
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

#ifndef DRIVER_X9CXX_H
#define DRIVER_X9CXX_H

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#ifdef __cplusplus
extern "C"{
#endif

/**
 * @defgroup x9cxx_driver x9cxx driver function
 * @brief    x9cxx driver modules
 * @{
 */

/**
 * @addtogroup x9cxx_basic_driver
 * @{
 */

/**
 * @brief x9cxx step delay definition
 */
#ifndef X9CXX_STEP_DELAY_US
    #define X9CXX_STEP_DELAY_US        10         /**< 10us */
#endif

/**
 * @brief x9cxx operate delay definition
 */
#ifndef X9CXX_OPERATE_DELAY_US
    #define X9CXX_OPERATE_DELAY_US        10         /**< 10us */
#endif

/**
 * @brief x9cxx store delay definition
 */
#ifndef X9CXX_STORE_DELAY_MS
    #define X9CXX_STORE_DELAY_MS        30        /**< 30ms */
#endif

/**
 * @brief x9cxx type enumeration definition
 */
typedef enum
{
    X9C102 = 1000,          /**< 1k */
    X9C103 = 10000,         /**< 10k */
    X9C503 = 50000,         /**< 50k */
    X9C104 = 100000,        /**< 100k */
} x9cxx_type_t;

/**
 * @brief x9cxx bool enumeration definition
 */
typedef enum
{
    X9CXX_BOOL_FALSE = 0x00,        /**< false */
    X9CXX_BOOL_TRUE  = 0x01,        /**< true */
} x9cxx_bool_t;

/**
 * @brief x9cxx handle structure definition
 */
typedef struct x9cxx_handle_s
{
    uint8_t (*cs_gpio_init)(void);                          /**< point to a cs_gpio_init function address */
    uint8_t (*cs_gpio_deinit)(void);                        /**< point to a cs_gpio_deinit function address */
    uint8_t (*cs_gpio_write)(uint8_t value);                /**< point to a cs_gpio_write function address */
    uint8_t (*up_down_gpio_init)(void);                     /**< point to an up_down_gpio_init function address */
    uint8_t (*up_down_gpio_deinit)(void);                   /**< point to an up_down_gpio_deinit function address */
    uint8_t (*up_down_gpio_write)(uint8_t value);           /**< point to an up_down_gpio_write function address */
    uint8_t (*inc_gpio_init)(void);                         /**< point to an inc_gpio_init function address */
    uint8_t (*inc_gpio_deinit)(void);                       /**< point to an inc_gpio_deinit function address */
    uint8_t (*inc_gpio_write)(uint8_t value);               /**< point to an inc_gpio_write function address */
    void (*debug_print)(const char *const fmt, ...);        /**< point to a debug_print function address */
    void (*delay_ms)(uint32_t ms);                          /**< point to a delay_ms function address */
    void (*delay_us)(uint32_t us);                          /**< point to a delay_us function address */
    uint8_t inited;                                         /**< inited flag */
    uint8_t valid;                                          /**< valid */
    uint8_t step;                                           /**< step */
    uint32_t type;                                          /**< type */
} x9cxx_handle_t;

/**
 * @brief x9cxx information structure definition
 */
typedef struct x9cxx_info_s
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
} x9cxx_info_t;

/**
 * @}
 */

/**
 * @defgroup x9cxx_link_driver x9cxx link driver function
 * @brief    x9cxx link driver modules
 * @ingroup  x9cxx_driver
 * @{
 */

/**
 * @brief     initialize x9cxx_handle_t structure
 * @param[in] HANDLE pointer to a x9cxx handle structure
 * @param[in] STRUCTURE x9cxx_handle_t
 * @note      none
 */
#define DRIVER_X9CXX_LINK_INIT(HANDLE, STRUCTURE)              memset(HANDLE, 0, sizeof(STRUCTURE))

/**
 * @brief     link cs_gpio_init function
 * @param[in] HANDLE pointer to a x9cxx handle structure
 * @param[in] FUC pointer to a cs_gpio_init function address
 * @note      none
 */
#define DRIVER_X9CXX_LINK_CS_GPIO_INIT(HANDLE, FUC)           (HANDLE)->cs_gpio_init = FUC

/**
 * @brief     link cs_gpio_deinit function
 * @param[in] HANDLE pointer to a x9cxx handle structure
 * @param[in] FUC pointer to a cs_gpio_deinit function address
 * @note      none
 */
#define DRIVER_X9CXX_LINK_CS_GPIO_DEINIT(HANDLE, FUC)         (HANDLE)->cs_gpio_deinit = FUC

/**
 * @brief     link cs_gpio_write function
 * @param[in] HANDLE pointer to a x9cxx handle structure
 * @param[in] FUC pointer to a cs_gpio_write function address
 * @note      none
 */
#define DRIVER_X9CXX_LINK_CS_GPIO_WRITE(HANDLE, FUC)          (HANDLE)->cs_gpio_write = FUC

/**
 * @brief     link up_down_gpio_init function
 * @param[in] HANDLE pointer to a x9cxx handle structure
 * @param[in] FUC pointer to an up_down_gpio_init function address
 * @note      none
 */
#define DRIVER_X9CXX_LINK_UP_DOWN_GPIO_INIT(HANDLE, FUC)      (HANDLE)->up_down_gpio_init = FUC

/**
 * @brief     link up_down_gpio_deinit function
 * @param[in] HANDLE pointer to a x9cxx handle structure
 * @param[in] FUC pointer to an up_down_gpio_deinit function address
 * @note      none
 */
#define DRIVER_X9CXX_LINK_UP_DOWN_GPIO_DEINIT(HANDLE, FUC)    (HANDLE)->up_down_gpio_deinit = FUC

/**
 * @brief     link up_down_gpio_write function
 * @param[in] HANDLE pointer to a x9cxx handle structure
 * @param[in] FUC pointer to an up_down_gpio_write function address
 * @note      none
 */
#define DRIVER_X9CXX_LINK_UP_DOWN_GPIO_WRITE(HANDLE, FUC)     (HANDLE)->up_down_gpio_write = FUC

/**
 * @brief     link inc_gpio_init function
 * @param[in] HANDLE pointer to a x9cxx handle structure
 * @param[in] FUC pointer to an inc_gpio_init function address
 * @note      none
 */
#define DRIVER_X9CXX_LINK_INC_GPIO_INIT(HANDLE, FUC)          (HANDLE)->inc_gpio_init = FUC

/**
 * @brief     link inc_gpio_deinit function
 * @param[in] HANDLE pointer to a x9cxx handle structure
 * @param[in] FUC pointer to a inc_gpio_deinit function address
 * @note      none
 */
#define DRIVER_X9CXX_LINK_INC_GPIO_DEINIT(HANDLE, FUC)        (HANDLE)->inc_gpio_deinit = FUC

/**
 * @brief     link inc_gpio_write function
 * @param[in] HANDLE pointer to a x9cxx handle structure
 * @param[in] FUC pointer to an inc_gpio_write function address
 * @note      none
 */
#define DRIVER_X9CXX_LINK_INC_GPIO_WRITE(HANDLE, FUC)         (HANDLE)->inc_gpio_write = FUC

/**
 * @brief     link debug_print function
 * @param[in] HANDLE pointer to a x9cxx handle structure
 * @param[in] FUC pointer to a debug_print function address
 * @note      none
 */
#define DRIVER_X9CXX_LINK_DEBUG_PRINT(HANDLE, FUC)            (HANDLE)->debug_print = FUC

/**
 * @brief     link delay_ms function
 * @param[in] HANDLE pointer to a x9cxx handle structure
 * @param[in] FUC pointer to a delay_ms function address
 * @note      none
 */
#define DRIVER_X9CXX_LINK_DELAY_MS(HANDLE, FUC)               (HANDLE)->delay_ms = FUC

/**
 * @brief     link delay_us function
 * @param[in] HANDLE pointer to a x9cxx handle structure
 * @param[in] FUC pointer to a delay_us function address
 * @note      none
 */
#define DRIVER_X9CXX_LINK_DELAY_US(HANDLE, FUC)               (HANDLE)->delay_us = FUC

/**
 * @}
 */

/**
 * @defgroup x9cxx_basic_driver x9cxx basic driver function
 * @brief    x9cxx basic driver modules
 * @ingroup  x9cxx_driver
 * @{
 */

/**
 * @brief      get chip's information
 * @param[out] *info pointer to a x9cxx info structure
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 * @note       none
 */
uint8_t x9cxx_info(x9cxx_info_t *info);

/**
 * @brief     set chip type
 * @param[in] *handle pointer to a x9cxx handle structure
 * @param[in] type chip type
 * @return    status code
 *            - 0 success
 *            - 2 handle is NULL
 * @note      none
 */
uint8_t x9cxx_set_type(x9cxx_handle_t *handle, x9cxx_type_t type);

/**
 * @brief      get chip type
 * @param[in]  *handle pointer to a x9cxx handle structure
 * @param[out] *type pointer to a chip type buffer
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 * @note       none
 */
uint8_t x9cxx_get_type(x9cxx_handle_t *handle, x9cxx_type_t *type);

/**
 * @brief     initialize the chip
 * @param[in] *handle pointer to a x9cxx handle structure
 * @return    status code
 *            - 0 success
 *            - 1 gpio initialization failed
 *            - 2 handle is NULL
 *            - 3 linked functions is NULL
 * @note      none
 */
uint8_t x9cxx_init(x9cxx_handle_t *handle);

/**
 * @brief     close the chip
 * @param[in] *handle pointer to a x9cxx handle structure
 * @return    status code
 *            - 0 success
 *            - 1 deinit failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t x9cxx_deinit(x9cxx_handle_t *handle);

/**
 * @brief     reset to min
 * @param[in] *handle pointer to a x9cxx handle structure
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 reset failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      this function can make step counter valid
 */
uint8_t x9cxx_reset_to_min(x9cxx_handle_t *handle, x9cxx_bool_t store_enable);

/**
 * @brief     reset to max
 * @param[in] *handle pointer to a x9cxx handle structure
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 reset failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      this function can make step counter valid
 */
uint8_t x9cxx_reset_to_max(x9cxx_handle_t *handle, x9cxx_bool_t store_enable);

/**
 * @brief     increment
 * @param[in] *handle pointer to a x9cxx handle structure
 * @param[in] step step counter
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 increment failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t x9cxx_increment(x9cxx_handle_t *handle, uint8_t step, x9cxx_bool_t store_enable);

/**
 * @brief     decrement
 * @param[in] *handle pointer to a x9cxx handle structure
 * @param[in] step step counter
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 decrement failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t x9cxx_decrement(x9cxx_handle_t *handle, uint8_t step, x9cxx_bool_t store_enable);

/**
 * @brief     set absolute step counter
 * @param[in] *handle pointer to a x9cxx handle structure
 * @param[in] counter absolute step counter
 * @param[in] store_enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 set absolute step counter failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 *            - 4 step counter is invalid
 *            - 5 counter > 99
 * @note      you must run x9cxx_reset_to_min or x9cxx_reset_to_max to
 *            make step counter valid
 *            0 <= counter <= 99
 */
uint8_t x9cxx_set_absolute_step_counter(x9cxx_handle_t *handle, uint8_t counter, x9cxx_bool_t store_enable);

/**
 * @brief      get step counter
 * @param[in]  *handle pointer to a x9cxx handle structure
 * @param[out] *counter pointer to a step counter buffer 
 * @return     status code
 *             - 0 success
 *             - 1 step counter is invalid
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t x9cxx_get_step_counter(x9cxx_handle_t *handle, uint8_t *counter);

/**
 * @brief      resistor convert to register
 * @param[in]  *handle pointer to a x9cxx handle structure
 * @param[in]  ohm resistor ohm
 * @param[out] *step pointer to a step buffer
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t x9cxx_resistor_convert_to_register(x9cxx_handle_t *handle, float ohm, uint8_t *step);

/**
 * @brief      resistor convert to data
 * @param[in]  *handle pointer to a x9cxx handle structure
 * @param[in]  step step counter
 * @param[out] *ohm pointer to an ohm buffer
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t x9cxx_resistor_convert_to_data(x9cxx_handle_t *handle, uint8_t step, float *ohm);

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
