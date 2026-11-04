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
 * @file      driver_tlc5615.c
 * @brief     driver tlc5615 source file
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

#include "driver_tlc5615.h"

/**
 * @brief chip register definition
 */
#define CHIP_NAME                 "Texas Instruments TLC5615"        /**< chip name */
#define MANUFACTURER_NAME         "Texas Instruments"                /**< manufacturer name */
#define SUPPLY_VOLTAGE_MIN        4.5f                               /**< chip min supply voltage */
#define SUPPLY_VOLTAGE_MAX        5.5f                               /**< chip max supply voltage */
#define MAX_CURRENT               20.0f                              /**< chip max current */
#define TEMPERATURE_MIN           -40.0f                             /**< chip min operating temperature */
#define TEMPERATURE_MAX           85.0f                              /**< chip max operating temperature */
#define DRIVER_VERSION            1000                               /**< driver version */

/**
 * @brief     spi write
 * @param[in] *handle pointer to a tlc5615 handle structure
 * @param[in] *buf pointer to a data buffer
 * @param[in] len buffer length
 * @return    status code
 *            - 0 success
 *            - 1 write failed
 * @note      none
 */
static uint8_t a_tlc5615_spi_write(tlc5615_handle_t *handle, uint8_t *buf, uint16_t len)
{
    if (handle->spi_write_cmd(buf, len) != 0)        /* spi write */
    {
        return 1;                                    /* return error */
    }
    
    return 0;                                        /* success return 0 */
}

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
uint8_t tlc5615_init(tlc5615_handle_t *handle)
{
    if (handle == NULL)                                                  /* check handle */
    {
        return 2;                                                        /* return error */
    }
    if (handle->debug_print == NULL)                                     /* check debug_print */
    {
        return 3;                                                        /* return error */
    }
    if (handle->spi_init == NULL)                                        /* check spi_init */
    {
        handle->debug_print("tlc5615: spi_init is null.\n");             /* spi_init is null */
       
        return 3;                                                        /* return error */
    }
    if (handle->spi_deinit == NULL)                                      /* check spi_deinit */
    {
        handle->debug_print("tlc5615: spi_deinit is null.\n");           /* spi_deinit is null */
       
        return 3;                                                        /* return error */
    }
    if (handle->spi_write_cmd == NULL)                                   /* check spi_write_cmd */
    {
        handle->debug_print("tlc5615: spi_write_cmd is null.\n");        /* spi_write_cmd is null */
       
        return 3;                                                        /* return error */
    }
    if (handle->delay_ms == NULL)                                        /* check delay_ms */
    {
        handle->debug_print("tlc5615: delay_ms is null.\n");             /* delay_ms is null */
       
        return 3;                                                        /* return error */
    }
    
    if (handle->spi_init() != 0)                                         /* spi init */
    {
        handle->debug_print("tlc5615: spi init failed.\n");              /* spi init failed */
       
        return 1;                                                        /* return error */
    }
    handle->reference_voltage = 0.0f;                                    /* init 0.0f */
    handle->inited = 1;                                                  /* flag finish initialization */
    
    return 0;                                                            /* success return 0 */
}

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
uint8_t tlc5615_set_reference_voltage(tlc5615_handle_t *handle, float voltage_v)
{
    if (handle == NULL)                           /* check handle */
    {
        return 2;                                 /* return error */
    }
    if (handle->inited != 1)                      /* check handle initialization */
    {
        return 3;                                 /* return error */
    }
    
    handle->reference_voltage = voltage_v;        /* set reference voltage */
    
    return 0;                                     /* success return 0 */
}

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
uint8_t tlc5615_get_reference_voltage(tlc5615_handle_t *handle, float *voltage_v)
{
    if (handle == NULL)                            /* check handle */
    {
        return 2;                                  /* return error */
    }
    if (handle->inited != 1)                       /* check handle initialization */
    {
        return 3;                                  /* return error */
    }
    
    *voltage_v = handle->reference_voltage;        /* set reference voltage */
    
    return 0;                                      /* success return 0 */
}

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
uint8_t tlc5615_voltage_convert_to_register(tlc5615_handle_t *handle, float volt, uint16_t *reg)
{
    if (handle == NULL)                                                           /* check handle */
    {
        return 2;                                                                 /* return error */
    }
    if (handle->inited != 1)                                                      /* check handle initialization */
    {
        return 3;                                                                 /* return error */
    }
    
    *reg = (uint16_t)((volt / (2 * handle->reference_voltage)) * 1024.0f);        /* convert */
    
    return 0;                                                                     /* success return 0 */
}

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
uint8_t tlc5615_voltage_convert_to_data(tlc5615_handle_t *handle, uint16_t reg, float *volt)
{
    if (handle == NULL)                                                       /* check handle */
    {
        return 2;                                                             /* return error */
    }
    if (handle->inited != 1)                                                  /* check handle initialization */
    {
        return 3;                                                             /* return error */
    }
    
    *volt = 2.0f * handle->reference_voltage * (float)(reg) / 1024.0f;        /* convert */
    
    return 0;                                                                 /* success return 0 */
}

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
uint8_t tlc5615_write(tlc5615_handle_t *handle, uint16_t reg)
{
    uint8_t res;
    uint8_t buf[2];
    uint16_t prev;
    
    if (handle == NULL)                                         /* check handle */
    {
        return 2;                                               /* return error */
    }
    if (handle->inited != 1)                                    /* check handle initialization */
    {
        return 3;                                               /* return error */
    }
    if (reg > 1023)                                             /* check range */
    {
        handle->debug_print("tlc5615: reg > 1023.\n");          /* reg > 1023 */
        
        return 4;                                               /* return error */
    }
    
    prev = (reg & 0x3FF) << 2;                                  /* set data */
    buf[0] = (prev >> 8) & 0xFF;                                /* set msb */
    buf[1] = (prev >> 0) & 0xFF;                                /* set lsb */
    res = a_tlc5615_spi_write(handle, buf, 2);                  /* write data */
    if (res != 0)                                               /* check the result */
    {
        handle->debug_print("tlc5615: write failed.\n");        /* write failed */
       
        return 1;                                               /* return error */
    }
    
    return 0;                                                   /* success return 0 */
}

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
uint8_t tlc5615_deinit(tlc5615_handle_t *handle)
{
    uint8_t res;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = handle->spi_deinit();                                      /* spi deinit */
    if (res != 0)                                                    /* check error */
    {
        handle->debug_print("tlc5615: spi deinit failed.\n");        /* spi deinit failed */
       
        return 1;                                                    /* return error */
    }
    handle->inited = 0;                                              /* flag closed */
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t tlc5615_set_reg(tlc5615_handle_t *handle, uint8_t *buf, uint16_t len)
{
    if (handle == NULL)                                  /* check handle */
    {
        return 2;                                        /* return error */
    }
    if (handle->inited != 1)                             /* check handle initialization */
    {
        return 3;                                        /* return error */
    }
    
    return a_tlc5615_spi_write(handle, buf, len);        /* write to reg */
}

/**
 * @brief      get chip's information
 * @param[out] *info pointer to a tlc5615 info structure
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 * @note       none
 */
uint8_t tlc5615_info(tlc5615_info_t *info)
{
    if (info == NULL)                                               /* check handle */
    {
        return 2;                                                   /* return error */
    }
    
    memset(info, 0, sizeof(tlc5615_info_t));                        /* initialize tlc5615 info structure */
    strncpy(info->chip_name, CHIP_NAME, 32);                        /* copy chip name */
    strncpy(info->manufacturer_name, MANUFACTURER_NAME, 32);        /* copy manufacturer name */
    strncpy(info->interface, "SPI", 8);                             /* copy interface name */
    info->supply_voltage_min_v = SUPPLY_VOLTAGE_MIN;                /* set minimal supply voltage */
    info->supply_voltage_max_v = SUPPLY_VOLTAGE_MAX;                /* set maximum supply voltage */
    info->max_current_ma = MAX_CURRENT;                             /* set maximum current */
    info->temperature_max = TEMPERATURE_MAX;                        /* set maximum temperature */
    info->temperature_min = TEMPERATURE_MIN;                        /* set minimal temperature */
    info->driver_version = DRIVER_VERSION;                          /* set driver version */
    
    return 0;                                                       /* success return 0 */
}
