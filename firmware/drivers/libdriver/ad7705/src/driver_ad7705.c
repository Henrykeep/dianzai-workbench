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
 * @file      driver_ad7705.c
 * @brief     driver ad7705 source file
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

#include "driver_ad7705.h"
#include <math.h>

/**
 * @brief chip information definition
 */
#define CHIP_NAME                 "Analog Devices AD7705"        /**< chip name */
#define MANUFACTURER_NAME         "Analog Devices"               /**< manufacturer name */
#define SUPPLY_VOLTAGE_MIN        2.7f                           /**< chip min supply voltage */
#define SUPPLY_VOLTAGE_MAX        5.25f                          /**< chip max supply voltage */
#define MAX_CURRENT               1.3f                           /**< chip max current */
#define TEMPERATURE_MIN           -20.0f                         /**< chip min operating temperature */
#define TEMPERATURE_MAX           85.0f                          /**< chip max operating temperature */
#define DRIVER_VERSION            1000                           /**< driver version */

/**
 * @brief chip register definition
 */
#define AD7705_REG_COMMUNICATION        0x00        /**< communication register */
#define AD7705_REG_SETUP                0x01        /**< setup register */
#define AD7705_REG_CLOCK                0x02        /**< clock register */
#define AD7705_REG_DATA                 0x03        /**< data register */
#define AD7705_REG_TEST                 0x04        /**< test register */
#define AD7705_REG_NO_OPERATION         0x05        /**< no operation register */
#define AD7705_REG_OFFSET               0x06        /**< offset register */
#define AD7705_REG_GAIN                 0x07        /**< gain register */

/**
 * @brief      read bytes
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[in]  addr address
 * @param[out] *buf pointer to a data buffer
 * @param[in]  len buffer length
 * @return     status code
 *             - 0 success
 *             - 1 spi read failed
 * @note       none
 */
static uint8_t a_ad7705_read(ad7705_handle_t *handle, uint8_t addr, uint8_t *buf, uint16_t len)
{
    uint8_t command;
    
    command = ((addr & 0x7) << 4) | (1 << 3) |
              (handle->standby << 2) | (handle->channel & 0x03);        /* make command */
    if (handle->spi_read(command, buf, len) != 0)                       /* read data */
    {
        return 1;                                                       /* return error */
    }
    
    return 0;                                                           /* success return 0 */
}

/**
 * @brief     write bytes
 * @param[in] *handle pointer to an ad7705 handle structure
 * @param[in] addr address
 * @param[in] *buf pointer to a data buffer
 * @param[in] len buffer length
 * @return    status code
 *            - 0 success
 *            - 1 spi write failed
 * @note      none
 */
static uint8_t a_ad7705_write(ad7705_handle_t *handle, uint8_t addr, uint8_t *buf, uint16_t len)
{
    uint8_t command;
    
    command = ((addr & 0x7) << 4) |
              (handle->standby << 2) | (handle->channel & 0x03);        /* make command */
    if (handle->spi_write(command, buf, len) != 0)                      /* write data */
    {
        return 1;                                                       /* return error */
    }
    
    return 0;                                                           /* success return 0 */
}

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
uint8_t ad7705_set_channel(ad7705_handle_t *handle, ad7705_channel_t channel)
{
    if (handle == NULL)                        /* check handle */
    {
        return 2;                              /* return error */
    }
    if (handle->inited != 1)                   /* check handle initialization */
    {
        return 3;                              /* return error */
    }
    
    handle->channel = (uint8_t)channel;        /* set channel */
    
    return 0;                                  /* success return 0 */
}

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
uint8_t ad7705_get_channel(ad7705_handle_t *handle, ad7705_channel_t *channel)
{
    if (handle == NULL)                                    /* check handle */
    {
        return 2;                                          /* return error */
    }
    if (handle->inited != 1)                               /* check handle initialization */
    {
        return 3;                                          /* return error */
    }
    
    *channel = (ad7705_channel_t)(handle->channel);        /* set channel */
    
    return 0;                                              /* success return 0 */
}

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
uint8_t ad7705_power_down(ad7705_handle_t *handle)
{
    uint8_t res;
    
    if (handle == NULL)                                                    /* check handle */
    {
        return 2;                                                          /* return error */
    }
    if (handle->inited != 1)                                               /* check handle initialization */
    {
        return 3;                                                          /* return error */
    }
    
    handle->standby = 1;                                                   /* set enable */
    res = a_ad7705_write(handle, AD7705_REG_NO_OPERATION, NULL, 0);        /* write data */
    if (res != 0)                                                          /* check result */
    {
        handle->debug_print("ad7705: power down failed.\n");               /* power down failed */
       
        return 1;                                                          /* return error */
    }
    
    return 0;                                                              /* success return 0 */
}

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
uint8_t ad7705_power_on(ad7705_handle_t *handle)
{
    uint8_t res;
    
    if (handle == NULL)                                                    /* check handle */
    {
        return 2;                                                          /* return error */
    }
    if (handle->inited != 1)                                               /* check handle initialization */
    {
        return 3;                                                          /* return error */
    }
    
    handle->standby = 0;                                                   /* set disable */
    res = a_ad7705_write(handle, AD7705_REG_NO_OPERATION, NULL, 0);        /* write data */
    if (res != 0)                                                          /* check result */
    {
        handle->debug_print("ad7705: power on failed.\n");                 /* power on failed */
       
        return 1;                                                          /* return error */
    }
    handle->delay_ms(10);                                                  /* delay 10ms */
    
    return 0;                                                              /* success return 0 */
}

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
uint8_t ad7705_set_adc_mode(ad7705_handle_t *handle, ad7705_adc_mode_t mode)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_SETUP, &prev, 1);         /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read setup failed.\n");         /* read setup failed */
       
        return 1;                                                    /* return error */
    }
    prev &= ~(3 << 6);                                               /* clear settings */
    prev |= mode << 6;                                               /* set mode */
    res = a_ad7705_write(handle, AD7705_REG_SETUP, &prev, 1);        /* write data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: write setup failed.\n");        /* write setup failed */
       
        return 1;                                                    /* return error */
    }
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_get_adc_mode(ad7705_handle_t *handle, ad7705_adc_mode_t *mode)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_SETUP, &prev, 1);         /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read setup failed.\n");         /* read setup failed */
       
        return 1;                                                    /* return error */
    }
    *mode = (ad7705_adc_mode_t)((prev >> 6) & 0x03);                 /* set mode */
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_set_adc_gain(ad7705_handle_t *handle, ad7705_adc_gain_t gain)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_SETUP, &prev, 1);         /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read setup failed.\n");         /* read setup failed */
       
        return 1;                                                    /* return error */
    }
    prev &= ~(7 << 3);                                               /* clear settings */
    prev |= gain << 3;                                               /* set gain */
    res = a_ad7705_write(handle, AD7705_REG_SETUP, &prev, 1);        /* write data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: write setup failed.\n");        /* write setup failed */
       
        return 1;                                                    /* return error */
    }
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_get_adc_gain(ad7705_handle_t *handle, ad7705_adc_gain_t *gain)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_SETUP, &prev, 1);         /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read setup failed.\n");         /* read setup failed */
       
        return 1;                                                    /* return error */
    }
    *gain = (ad7705_adc_gain_t)((prev >> 3) & 0x07);                 /* set gain */
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_set_adc_polar(ad7705_handle_t *handle, ad7705_adc_polar_t polar)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_SETUP, &prev, 1);         /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read setup failed.\n");         /* read setup failed */
       
        return 1;                                                    /* return error */
    }
    prev &= ~(1 << 2);                                               /* clear settings */
    prev |= polar << 2;                                              /* set polar */
    res = a_ad7705_write(handle, AD7705_REG_SETUP, &prev, 1);        /* write data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: write setup failed.\n");        /* write setup failed */
       
        return 1;                                                    /* return error */
    }
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_get_adc_polar(ad7705_handle_t *handle, ad7705_adc_polar_t *polar)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_SETUP, &prev, 1);         /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read setup failed.\n");         /* read setup failed */
       
        return 1;                                                    /* return error */
    }
    *polar = (ad7705_adc_polar_t)((prev >> 2) & 0x01);               /* set polar */
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_set_adc_buffer(ad7705_handle_t *handle, ad7705_bool_t enable)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_SETUP, &prev, 1);         /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read setup failed.\n");         /* read setup failed */
       
        return 1;                                                    /* return error */
    }
    prev &= ~(1 << 1);                                               /* clear settings */
    prev |= enable << 1;                                             /* set bool */
    res = a_ad7705_write(handle, AD7705_REG_SETUP, &prev, 1);        /* write data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: write setup failed.\n");        /* write setup failed */
       
        return 1;                                                    /* return error */
    }
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_get_adc_buffer(ad7705_handle_t *handle, ad7705_bool_t *enable)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_SETUP, &prev, 1);         /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read setup failed.\n");         /* read setup failed */
       
        return 1;                                                    /* return error */
    }
    *enable = (ad7705_bool_t)((prev >> 1) & 0x01);                   /* set buffer */
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_set_filter_synchronize(ad7705_handle_t *handle, ad7705_bool_t enable)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_SETUP, &prev, 1);         /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read setup failed.\n");         /* read setup failed */
       
        return 1;                                                    /* return error */
    }
    prev &= ~(1 << 0);                                               /* clear settings */
    prev |= (!enable) << 0;                                          /* set bool */
    res = a_ad7705_write(handle, AD7705_REG_SETUP, &prev, 1);        /* write data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: write setup failed.\n");        /* write setup failed */
       
        return 1;                                                    /* return error */
    }
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_get_filter_synchronize(ad7705_handle_t *handle, ad7705_bool_t *enable)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_SETUP, &prev, 1);         /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read setup failed.\n");         /* read setup failed */
       
        return 1;                                                    /* return error */
    }
    *enable = (ad7705_bool_t)(!((prev >> 0) & 0x01));                /* set bool */
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_set_master_clock_output_disable(ad7705_handle_t *handle, ad7705_bool_t enable)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_CLOCK, &prev, 1);         /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read clock failed.\n");         /* read clock failed */
       
        return 1;                                                    /* return error */
    }
    prev &= ~(7 << 5);                                               /* all set zeros */
    prev &= ~(1 << 4);                                               /* clear settings */
    prev |= enable << 4;                                             /* set bool */
    res = a_ad7705_write(handle, AD7705_REG_CLOCK, &prev, 1);        /* write data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: write clock failed.\n");        /* write clock failed */
       
        return 1;                                                    /* return error */
    }
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_get_master_clock_output_disable(ad7705_handle_t *handle, ad7705_bool_t *enable)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_CLOCK, &prev, 1);         /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read clock failed.\n");         /* read clock failed */
       
        return 1;                                                    /* return error */
    }
    *enable = (ad7705_bool_t)((prev >> 4) & 0x01);                   /* set bool */
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_set_clock_div2(ad7705_handle_t *handle, ad7705_bool_t enable)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_CLOCK, &prev, 1);         /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read clock failed.\n");         /* read clock failed */
       
        return 1;                                                    /* return error */
    }
    prev &= ~(7 << 5);                                               /* all set zeros */
    prev &= ~(1 << 3);                                               /* clear settings */
    prev |= enable << 3;                                             /* set bool */
    res = a_ad7705_write(handle, AD7705_REG_CLOCK, &prev, 1);        /* write data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: write clock failed.\n");        /* write clock failed */
       
        return 1;                                                    /* return error */
    }
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_get_clock_div2(ad7705_handle_t *handle, ad7705_bool_t *enable)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_CLOCK, &prev, 1);         /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read clock failed.\n");         /* read clock failed */
       
        return 1;                                                    /* return error */
    }
    *enable = (ad7705_bool_t)((prev >> 3) & 0x01);                   /* set bool */
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_set_rate(ad7705_handle_t *handle, ad7705_rate_t rate)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_CLOCK, &prev, 1);         /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read clock failed.\n");         /* read clock failed */
       
        return 1;                                                    /* return error */
    }
    prev &= ~(7 << 5);                                               /* all set zeros */
    prev &= ~(7 << 0);                                               /* clear settings */
    prev |= rate << 0;                                               /* set rate */
    res = a_ad7705_write(handle, AD7705_REG_CLOCK, &prev, 1);        /* write data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: write clock failed.\n");        /* write clock failed */
       
        return 1;                                                    /* return error */
    }
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_get_rate(ad7705_handle_t *handle, ad7705_rate_t *rate)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_CLOCK, &prev, 1);         /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read clock failed.\n");         /* read clock failed */
       
        return 1;                                                    /* return error */
    }
    *rate = (ad7705_rate_t)(prev & 0x07);                            /* set rate */
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_get_data(ad7705_handle_t *handle, uint16_t *data)
{
    uint8_t res;
    uint8_t buf[2];
    
    if (handle == NULL)                                            /* check handle */
    {
        return 2;                                                  /* return error */
    }
    if (handle->inited != 1)                                       /* check handle initialization */
    {
        return 3;                                                  /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_DATA, buf, 2);          /* read data */
    if (res != 0)                                                  /* check result */
    {
        handle->debug_print("ad7705: read data failed.\n");        /* read data failed */
       
        return 1;                                                  /* return error */
    }
    *data = (uint16_t)((((uint16_t)buf[0]) << 8) | buf[1]);        /* set data */
    
    
    return 0;                                                      /* success return 0 */
}

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
uint8_t ad7705_set_test(ad7705_handle_t *handle, uint8_t data)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                             /* check handle */
    {
        return 2;                                                   /* return error */
    }
    if (handle->inited != 1)                                        /* check handle initialization */
    {
        return 3;                                                   /* return error */
    }
    
    prev = data;                                                    /* set data */
    res = a_ad7705_write(handle, AD7705_REG_TEST, &prev, 1);        /* write data */
    if (res != 0)                                                   /* check result */
    {
        handle->debug_print("ad7705: write test failed.\n");        /* write test failed */
       
        return 1;                                                   /* return error */
    }
    
    return 0;                                                       /* success return 0 */
}

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
uint8_t ad7705_get_test(ad7705_handle_t *handle, uint8_t *data)
{
    uint8_t res;
    
    if (handle == NULL)                                            /* check handle */
    {
        return 2;                                                  /* return error */
    }
    if (handle->inited != 1)                                       /* check handle initialization */
    {
        return 3;                                                  /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_TEST, data, 1);         /* read data */
    if (res != 0)                                                  /* check result */
    {
        handle->debug_print("ad7705: read test failed.\n");        /* read test failed */
       
        return 1;                                                  /* return error */
    }
    
    return 0;                                                      /* success return 0 */
}

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
uint8_t ad7705_set_zero_scale_calibration(ad7705_handle_t *handle, uint32_t calibration)
{
    uint8_t res;
    uint8_t buf[3];
    
    if (handle == NULL)                                               /* check handle */
    {
        return 2;                                                     /* return error */
    }
    if (handle->inited != 1)                                          /* check handle initialization */
    {
        return 3;                                                     /* return error */
    }
    
    buf[0] = (calibration >> 16) & 0xFF;                              /* set part1 */
    buf[1] = (calibration >> 8) & 0xFF;                               /* set part2 */
    buf[2] = (calibration >> 0) & 0xFF;                               /* set part3 */
    res = a_ad7705_write(handle, AD7705_REG_OFFSET, buf, 3);          /* write data */
    if (res != 0)                                                     /* check result */
    {
        handle->debug_print("ad7705: write offset failed.\n");        /* write offset failed */
       
        return 1;                                                     /* return error */
    }
    
    return 0;                                                         /* success return 0 */
}

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
uint8_t ad7705_get_zero_scale_calibration(ad7705_handle_t *handle, uint32_t *calibration)
{
    uint8_t res;
    uint8_t buf[3];
    
    if (handle == NULL)                                              /* check handle */
    {
        return 2;                                                    /* return error */
    }
    if (handle->inited != 1)                                         /* check handle initialization */
    {
        return 3;                                                    /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_OFFSET, buf, 3);          /* read data */
    if (res != 0)                                                    /* check result */
    {
        handle->debug_print("ad7705: read offset failed.\n");        /* read offset failed */
       
        return 1;                                                    /* return error */
    }
    *calibration = (uint32_t)((uint32_t)buf[0] << 16) |
                   (uint32_t)((uint32_t)buf[1] << 8) |
                   (uint32_t)((uint32_t)buf[2] << 0);                /* set calibration */
    
    return 0;                                                        /* success return 0 */
}

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
uint8_t ad7705_set_full_scale_calibration(ad7705_handle_t *handle, uint32_t calibration)
{
    uint8_t res;
    uint8_t buf[3];
    
    if (handle == NULL)                                             /* check handle */
    {
        return 2;                                                   /* return error */
    }
    if (handle->inited != 1)                                        /* check handle initialization */
    {
        return 3;                                                   /* return error */
    }
    
    buf[0] = (calibration >> 16) & 0xFF;                            /* set part1 */
    buf[1] = (calibration >> 8) & 0xFF;                             /* set part2 */
    buf[2] = (calibration >> 0) & 0xFF;                             /* set part3 */
    res = a_ad7705_write(handle, AD7705_REG_GAIN, buf, 3);          /* write data */
    if (res != 0)                                                   /* check result */
    {
        handle->debug_print("ad7705: write gain failed.\n");        /* write gain failed */
       
        return 1;                                                   /* return error */
    }
    
    return 0;                                                       /* success return 0 */
}

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
uint8_t ad7705_get_full_scale_calibration(ad7705_handle_t *handle, uint32_t *calibration)
{
    uint8_t res;
    uint8_t buf[3];
    
    if (handle == NULL)                                            /* check handle */
    {
        return 2;                                                  /* return error */
    }
    if (handle->inited != 1)                                       /* check handle initialization */
    {
        return 3;                                                  /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_GAIN, buf, 3);          /* read data */
    if (res != 0)                                                  /* check result */
    {
        handle->debug_print("ad7705: read gain failed.\n");        /* read gain failed */
       
        return 1;                                                  /* return error */
    }
    *calibration = (uint32_t)((uint32_t)buf[0] << 16) |
                   (uint32_t)((uint32_t)buf[1] << 8) |
                   (uint32_t)((uint32_t)buf[2] << 0);              /* set calibration */
    
    return 0;                                                      /* success return 0 */
}

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
uint8_t ad7705_set_reference_voltage(ad7705_handle_t *handle, float voltage)
{
    if (handle == NULL)                         /* check handle */
    {
        return 2;                               /* return error */
    }
    if (handle->inited != 1)                    /* check handle initialization */
    {
        return 3;                               /* return error */
    }
    
    handle->reference_voltage = voltage;        /* set reference voltage */
    
    return 0;                                   /* success return 0 */
}

/**
 * @brief      get reference voltage
 * @param[in]  *handle pointer to an ad7705 handle structure
 * @param[out] *voltage pointer to a reference voltage buffer
 * @return     status code
 *             - 0 success
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note       none
 */
uint8_t ad7705_get_reference_voltage(ad7705_handle_t *handle, float *voltage)
{
    if (handle == NULL)                         /* check handle */
    {
        return 2;                               /* return error */
    }
    if (handle->inited != 1)                    /* check handle initialization */
    {
        return 3;                               /* return error */
    }
    
    *voltage = handle->reference_voltage;       /* set reference voltage */
    
    return 0;                                   /* success return 0 */
}

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
uint8_t ad7705_get_data_ready(ad7705_handle_t *handle, ad7705_bool_t *enable)
{
    uint8_t res;
    uint8_t prev;
    
    if (handle == NULL)                                                     /* check handle */
    {
        return 2;                                                           /* return error */
    }
    if (handle->inited != 1)                                                /* check handle initialization */
    {
        return 3;                                                           /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_COMMUNICATION, &prev, 1);        /* read data */
    if (res != 0)                                                           /* check result */
    {
        handle->debug_print("ad7705: read communication failed.\n");        /* read communication failed */
       
        return 1;                                                           /* return error */
    }
    *enable = (ad7705_bool_t)(!((prev >> 7) & 0x01));                       /* set bool */
    
    return 0;                                                               /* success return 0 */
}

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
uint8_t ad7705_read(ad7705_handle_t *handle, uint16_t *raw, float *volt)
{
    uint8_t res;
    uint8_t prev;
    uint8_t gain;
    uint8_t polar;
    uint16_t timeout;
    uint8_t buf[2];
    
    if (handle == NULL)                                                         /* check handle */
    {
        return 2;                                                               /* return error */
    }
    if (handle->inited != 1)                                                    /* check handle initialization */
    {
        return 3;                                                               /* return error */
    }
    
    res = a_ad7705_read(handle, AD7705_REG_SETUP, &prev, 1);                    /* read data */
    if (res != 0)                                                               /* check result */
    {
        handle->debug_print("ad7705: read setup failed.\n");                    /* read setup failed */
       
        return 1;                                                               /* return error */
    }
    polar = (prev >> 2) & 0x01;                                                 /* set polar */
    gain = (prev >> 3) & 0x07;                                                  /* set gain */
    
    timeout = 1000;                                                             /* set timeout 1s */
    while (timeout != 0)                                                        /* wait 1s */
    {
        res = a_ad7705_read(handle, AD7705_REG_COMMUNICATION, &prev, 1);        /* read data */
        if (res != 0)                                                           /* check result */
        {
            handle->debug_print("ad7705: read communication failed.\n");        /* read communication failed */
           
            return 1;                                                           /* return error */
        }
        if (((prev >> 7) & 0x01) == 0)                                          /* check flag */
        {
            break;                                                              /* break */
        }
        handle->delay_ms(1);                                                    /* delay 1ms */
        timeout--;                                                              /* timeout-- */
    }
    if (timeout == 0)                                                           /* check timeout */
    {
        handle->debug_print("ad7705: read timeout.\n");                         /* read timeout */
       
        return 4;                                                               /* return error */
    }

    res = a_ad7705_read(handle, AD7705_REG_DATA, buf, 2);                       /* read data */
    if (res != 0)                                                               /* check result */
    {
        handle->debug_print("ad7705: read data failed.\n");                     /* read data failed */
       
        return 1;                                                               /* return error */
    }
    if (polar != 0)                                                             /* unipolar */
    {
        *raw = (uint16_t)((((uint16_t)buf[0]) << 8) | buf[1]);                  /* set data */
        *volt = (float)(*raw) / 65536.0f * handle->reference_voltage /
                (float)powf(2.0f, (float)(gain));                               /* convert voltage */
    }
    else                                                                        /* bipolar */
    {
        *raw = (uint16_t)((((uint16_t)buf[0]) << 8) | buf[1]);                  /* set data */
        *volt = ((float)(*raw) - 32768.0f) / 32768.0f * 
                handle->reference_voltage / (float)powf(2.0f, (float)(gain));   /* convert voltage */
    }
    
    return 0;                                                                   /* success return 0 */
}

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
uint8_t ad7705_operate_sync(ad7705_handle_t *handle)
{
    uint8_t res;
    uint8_t prev;
    uint16_t timeout;
    
    if (handle == NULL)                                                         /* check handle */
    {
        return 2;                                                               /* return error */
    }
    if (handle->inited != 1)                                                    /* check handle initialization */
    {
        return 3;                                                               /* return error */
    }
    
    handle->delay_ms(100);                                                      /* delay 100ms */
    timeout = 100;                                                              /* set timeout 1s */
    while (timeout != 0)                                                        /* wait 1s */
    {
        res = a_ad7705_read(handle, AD7705_REG_COMMUNICATION, &prev, 1);        /* read data */
        if (res != 0)                                                           /* check result */
        {
            handle->debug_print("ad7705: read communication failed.\n");        /* read communication failed */
           
            return 1;                                                           /* return error */
        }
        if (((prev >> 7) & 0x01) == 0)                                          /* check flag */
        {
            break;                                                              /* break */
        }
        handle->delay_ms(10);                                                   /* delay 10ms */
        timeout--;                                                              /* timeout-- */
    }
    if (timeout == 0)                                                           /* check timeout */
    {
        handle->debug_print("ad7705: sync timeout.\n");                         /* sync timeout */
       
        return 4;                                                               /* return error */
    }
    
    return 0;                                                                   /* success return 0 */
}

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
uint8_t ad7705_init(ad7705_handle_t *handle)
{
    uint8_t res;
    
    if (handle == NULL)                                                    /* check handle */
    {
        return 2;                                                          /* return error */
    }
    if (handle->debug_print == NULL)                                       /* check debug_print */
    {
        return 3;                                                          /* return error */
    }
    if (handle->gpio_reset_init == NULL)                                   /* check gpio_reset_init */
    {
        handle->debug_print("ad7705: gpio_reset_init is null.\n");         /* gpio_reset_init is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->gpio_reset_deinit == NULL)                                 /* check gpio_reset_deinit */
    {
        handle->debug_print("ad7705: gpio_reset_deinit is null.\n");       /* gpio_reset_deinit is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->gpio_reset_write == NULL)                                  /* check gpio_reset_write */
    {
        handle->debug_print("ad7705: gpio_reset_write is null.\n");        /* gpio_reset_write is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->spi_init == NULL)                                          /* check spi_init */
    {
        handle->debug_print("ad7705: spi_init is null.\n");                /* spi_init is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->spi_deinit == NULL)                                        /* check spi_deinit */
    {
        handle->debug_print("ad7705: spi_deinit is null.\n");              /* spi_deinit is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->spi_read == NULL)                                          /* check spi_read */
    {
        handle->debug_print("ad7705: spi_read is null.\n");                /* spi_read is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->spi_write == NULL)                                         /* check spi_write */
    {
        handle->debug_print("ad7705: spi_write is null.\n");               /* spi_write is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->delay_ms == NULL)                                          /* check delay_ms */
    {
        handle->debug_print("ad7705: delay_ms is null.\n");                /* delay_ms is null */
       
        return 3;                                                          /* return error */
    }
    
    if (handle->gpio_reset_init() != 0)                                    /* gpio reset init */
    {
        handle->debug_print("ad7705: gpio reset init failed.\n");          /* gpio reset init failed */
        
        return 1;                                                          /* return error */
    }
    if (handle->spi_init() != 0)                                           /* spi init */
    {
        handle->debug_print("ad7705: spi init failed.\n");                 /* spi init failed */
        (void)handle->gpio_reset_deinit();                                 /* gpio reset deinit */
        
        return 1;                                                          /* return error */
    }
    
    res = handle->gpio_reset_write(1);                                     /* set high */
    if (res != 0)                                                          /* check result */
    {
        handle->debug_print("ad7705: gpio reset write failed.\n");         /* gpio reset write failed */
        (void)handle->gpio_reset_deinit();                                 /* gpio reset deinit */
        (void)handle->spi_deinit();                                        /* spi deinit */
        
        return 4;                                                          /* return error */
    }
    handle->delay_ms(10);                                                  /* delay 10ms */
    res = handle->gpio_reset_write(0);                                     /* set low */
    if (res != 0)                                                          /* check result */
    {
        handle->debug_print("ad7705: gpio reset write failed.\n");         /* gpio reset write failed */
        (void)handle->gpio_reset_deinit();                                 /* gpio reset deinit */
        (void)handle->spi_deinit();                                        /* spi deinit */
        
        return 4;                                                          /* return error */
    }
    handle->delay_ms(10);                                                  /* delay 10ms */
    res = handle->gpio_reset_write(1);                                     /* set high */
    if (res != 0)                                                          /* check result */
    {
        handle->debug_print("ad7705: gpio reset write failed.\n");         /* gpio reset write failed */
        (void)handle->gpio_reset_deinit();                                 /* gpio reset deinit */
        (void)handle->spi_deinit();                                        /* spi deinit */
        
        return 4;                                                          /* return error */
    }
    handle->delay_ms(10);                                                  /* delay 10ms */
    
    handle->standby = 0;                                                   /* power on */
    res = a_ad7705_write(handle, AD7705_REG_NO_OPERATION, NULL, 0);        /* write data */
    if (res != 0)                                                          /* check result */
    {
        handle->debug_print("ad7705: power on failed.\n");                 /* power on failed */
        (void)handle->gpio_reset_deinit();                                 /* gpio reset deinit */
        (void)handle->spi_deinit();                                        /* spi deinit */
        
        return 5;                                                          /* return error */
    }
    handle->delay_ms(10);                                                  /* delay 10ms */
    handle->inited = 1;                                                    /* flag finish initialization */
    
    return 0;                                                              /* success return 0 */
}

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
uint8_t ad7705_deinit(ad7705_handle_t *handle)
{
    uint8_t res;
    
    if (handle == NULL)                                                    /* check handle */
    {
        return 2;                                                          /* return error */
    }
    if (handle->inited != 1)                                               /* check handle initialization */
    {
        return 3;                                                          /* return error */
    }
    
    handle->standby = 1;                                                   /* power down */
    res = a_ad7705_write(handle, AD7705_REG_NO_OPERATION, NULL, 0);        /* write data */
    if (res != 0)                                                          /* check result */
    {
        handle->debug_print("ad7705: power down failed.\n");               /* power down failed */
       
        return 4;                                                          /* return error */
    }
    
    res = handle->spi_deinit();                                            /* spi deinit */
    if (res != 0)                                                          /* check result */
    {
        handle->debug_print("ad7705: spi deinit failed.\n");               /* spi deinit failed */
       
        return 1;                                                          /* return error */
    }
    handle->inited = 0;                                                    /* flag close */
    
    return 0;                                                              /* success return 0 */
}

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
uint8_t ad7705_set_reg(ad7705_handle_t *handle, uint8_t addr, uint8_t *buf, uint16_t len)
{
    if (handle == NULL)                                    /* check handle */
    {
        return 2;                                          /* return error */
    }
    if (handle->inited != 1)                               /* check handle initialization */
    {
        return 3;                                          /* return error */
    }
    
    if (a_ad7705_write(handle, addr, buf, len) != 0)       /* write data */
    {
        return 1;                                          /* return error */
    }
    
    return 0;                                              /* success return 0 */
}

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
uint8_t ad7705_get_reg(ad7705_handle_t *handle, uint8_t addr, uint8_t *buf, uint16_t len)
{
    if (handle == NULL)                                    /* check handle */
    {
        return 2;                                          /* return error */
    }
    if (handle->inited != 1)                               /* check handle initialization */
    {
        return 3;                                          /* return error */
    }
    
    if (a_ad7705_read(handle, addr, buf, len) != 0)        /* read data */
    {
        return 1;                                          /* return error */
    }
    
    return 0;                                              /* success return 0 */
}

/**
 * @brief      get chip's information
 * @param[out] *info pointer to an ad7705 info structure
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 * @note       none
 */
uint8_t ad7705_info(ad7705_info_t *info)
{
    if (info == NULL)                                               /* check handle */
    {
        return 2;                                                   /* return error */
    }
    
    memset(info, 0, sizeof(ad7705_info_t));                         /* initialize ad7705 info structure */
    strncpy(info->chip_name, CHIP_NAME, 32);                        /* copy chip name */
    strncpy(info->manufacturer_name, MANUFACTURER_NAME, 32);        /* copy manufacturer name */
    strncpy(info->interface, "SPI", 8);                             /* copy interface name */
    info->supply_voltage_min_v = SUPPLY_VOLTAGE_MIN;                /* set minimal supply voltage */
    info->supply_voltage_max_v = SUPPLY_VOLTAGE_MAX;                /* set maximum supply voltage */
    info->max_current_ma = MAX_CURRENT;                             /* set maximum current */
    info->temperature_max = TEMPERATURE_MAX;                        /* set minimal temperature */
    info->temperature_min = TEMPERATURE_MIN;                        /* set maximum temperature */
    info->driver_version = DRIVER_VERSION;                          /* set driver version */
    
    return 0;                                                       /* success return 0 */
}
