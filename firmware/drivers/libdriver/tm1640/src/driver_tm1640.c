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
 * @file      driver_tm1640.c
 * @brief     driver tm1640 source file
 * @version   1.0.0
 * @author    Shifeng Li
 * @date      2025-10-31
 *
 * <h3>history</h3>
 * <table>
 * <tr><th>Date        <th>Version  <th>Author      <th>Description
 * <tr><td>2025/10/31  <td>1.0      <td>Shifeng Li  <td>first upload
 * </table>
 */

#include "driver_tm1640.h"

/**
 * @brief chip information definition
 */
#define CHIP_NAME                 "Titan Micro Electronics TM1640"        /**< chip name */
#define MANUFACTURER_NAME         "Titan Micro Electronics"               /**< manufacturer name */
#define SUPPLY_VOLTAGE_MIN        3.0f                                    /**< chip min supply voltage */
#define SUPPLY_VOLTAGE_MAX        5.5f                                    /**< chip max supply voltage */
#define MAX_CURRENT               200.0f                                  /**< chip max current */
#define TEMPERATURE_MIN           -40.0f                                  /**< chip min operating temperature */
#define TEMPERATURE_MAX           85.0f                                   /**< chip max operating temperature */
#define DRIVER_VERSION            1000                                    /**< driver version */

/**
 * @brief chip command definition
 */
#define TM1640_COMMAND_DATA           (1 << 6)        /**< data command setting */
#define TM1640_COMMAND_DISPLAY        (2 << 6)        /**< display and control command setting */
#define TM1640_COMMAND_ADDRESS        (3 << 6)        /**< address command setting */

/**
 * @brief     start
 * @param[in] *handle pointer to a tm1640 handle structure
 * @return    status code
 *            - 0 success
 *            - 1 start failed
 * @note      none
 */
static uint8_t a_tm1640_start(tm1640_handle_t *handle)
{
    if (handle->din_gpio_write(1) != 0)                 /* din set high */
    {
        return 1;                                       /* return error */
    }
    if (handle->sclk_gpio_write(1) != 0)                /* sclk set high */
    {
        return 1;                                       /* return error */
    }
    handle->delay_us(TM1640_COMMAND_DATA_DELAY);        /* delay */
    if (handle->din_gpio_write(0) != 0)                 /* din set low */
    {
        return 1;                                       /* return error */
    }
    handle->delay_us(TM1640_COMMAND_DATA_DELAY);        /* delay */
    if (handle->sclk_gpio_write(0) != 0)                /* sclk set low */
    {
        return 1;                                       /* return error */
    }
    handle->delay_us(TM1640_COMMAND_DATA_DELAY);        /* delay */
    
    return 0;                                           /* success return 0 */
}

/**
 * @brief     stop
 * @param[in] *handle pointer to a tm1640 handle structure
 * @return    status code
 *            - 0 success
 *            - 1 stop failed
 * @note      none
 */
static uint8_t a_tm1640_stop(tm1640_handle_t *handle)
{
    if (handle->din_gpio_write(0) != 0)                 /* din set low */
    {
        return 1;                                       /* return error */
    }
    if (handle->sclk_gpio_write(1) != 0)                /* sclk set high */
    {
        return 1;                                       /* return error */
    }
    handle->delay_us(TM1640_COMMAND_DATA_DELAY);        /* delay */
    if (handle->din_gpio_write(1) != 0)                 /* din set high */
    {
        return 1;                                       /* return error */
    }
    handle->delay_us(TM1640_COMMAND_DATA_DELAY);        /* delay */
    
    return 0;                                           /* success return 0 */
}

/**
 * @brief     byte write
 * @param[in] *handle pointer to a tm1640 handle structure
 * @param[in] data input data
 * @return    status code
 *            - 0 success
 *            - 1 write failed
 * @note      none
 */
static uint8_t a_tm1640_byte(tm1640_handle_t *handle, uint8_t data)
{
    uint8_t i;
    uint8_t temp;
    
    temp = data;                                                /* set data */
    if (handle->din_gpio_write(0) != 0)                         /* din set low */
    {
        return 1;                                               /* return error */
    }
    if (handle->sclk_gpio_write(0) != 0)                        /* sclk set low */
    {
        return 1;                                               /* return error */
    }
    
    for (i = 0; i < 8; i++)                                     /* write 8 bits */
    {
        if (handle->sclk_gpio_write(0) != 0)                    /* sclk set low */
        {
            return 1;                                           /* return error */
        }
        handle->delay_us(TM1640_COMMAND_DATA_DELAY);            /* delay */
        if ((temp & 0x1) != 0)                                  /* set lsb */
        {
            if (handle->din_gpio_write(1) != 0)                 /* din set high */
            {
                return 1;                                       /* return error */
            }
            handle->delay_us(TM1640_COMMAND_DATA_DELAY);        /* delay */
        }
        else
        {
            if (handle->din_gpio_write(0) != 0)                 /* din set low */
            {
                return 1;                                       /* return error */
            }
            handle->delay_us(TM1640_COMMAND_DATA_DELAY);        /* delay */
        }
        if (handle->sclk_gpio_write(1) != 0)                    /* sclk set high */
        {
            return 1;                                           /* return error */
        }
        handle->delay_us(TM1640_COMMAND_DATA_DELAY);            /* delay */
        temp >>= 1;                                             /* right shift 1 */
    }
    
    if (handle->din_gpio_write(0) != 0)                         /* din set low */
    {
        return 1;                                               /* return error */
    }
    if (handle->sclk_gpio_write(0) != 0)                        /* sclk set low */
    {
        return 1;                                               /* return error */
    }
    
    return 0;                                                   /* success return 0 */
}

/**
 * @brief     bus write
 * @param[in] *handle pointer to a tm1640 handle structure
 * @param[in] cmd set command
 * @param[in] *buf pointer to a data buffer 
 * @param[in] len buffer length
 * @return    status code
 *            - 0 success
 *            - 1 write failed
 * @note      none
 */
static uint8_t a_tm1640_write(tm1640_handle_t *handle, uint8_t cmd, uint8_t *buf, uint16_t len)
{
    uint8_t res;
    uint16_t i;
    
    res = a_tm1640_start(handle);                   /* start */
    if (res != 0)                                   /* check result */
    {
        return 1;                                   /* return error */
    }
    
    res = a_tm1640_byte(handle, cmd);               /* write command */
    if (res != 0)                                   /* check result */
    {
        return 1;                                   /* return error */
    }
    
    for (i = 0; i < len; i++)                       /* write all */
    {
        res = a_tm1640_byte(handle, buf[i]);        /* write data */
        if (res != 0)                               /* check result */
        {
            return 1;                               /* return error */
        }
    }
    
    res = a_tm1640_stop(handle);                    /* stop */
    if (res != 0)                                   /* check result */
    {
        return 1;                                   /* return error */
    }
    
    return 0;                                       /* success return 0 */
}

/**
 * @brief     initialize the chip
 * @param[in] *handle pointer to a tm1640 handle structure
 * @return    status code
 *            - 0 success
 *            - 1 gpio initialization failed
 *            - 2 handle is NULL
 *            - 3 linked functions is NULL
 * @note      none
 */
uint8_t tm1640_init(tm1640_handle_t *handle)
{
    uint8_t res;
    uint8_t cmd;
    
    if (handle == NULL)                                                    /* check handle */
    {
        return 2;                                                          /* return error */
    }
    if (handle->debug_print == NULL)                                       /* check debug_print */
    {
        return 3;                                                          /* return error */
    }
    if (handle->sclk_gpio_init == NULL)                                    /* check sclk_gpio_init */
    {
        handle->debug_print("tm1640: sclk_gpio_init is null.\n");          /* sclk_gpio_init is null */
        
        return 3;                                                          /* return error */
    }
    if (handle->sclk_gpio_deinit == NULL)                                  /* check sclk_gpio_deinit */
    {
        handle->debug_print("tm1640: sclk_gpio_deinit is null.\n");        /* sclk_gpio_deinit is null */
        
        return 3;                                                          /* return error */
    }
    if (handle->sclk_gpio_write == NULL)                                   /* check sclk_gpio_write */
    {
        handle->debug_print("tm1640: sclk_gpio_write is null.\n");         /* sclk_gpio_write is null */
        
        return 3;                                                          /* return error */
    }
    if (handle->din_gpio_init == NULL)                                     /* check din_gpio_init */
    {
        handle->debug_print("tm1640: din_gpio_init is null.\n");           /* din_gpio_init is null */
        
        return 3;                                                          /* return error */
    }
    if (handle->din_gpio_deinit == NULL)                                   /* check din_gpio_deinit */
    {
        handle->debug_print("tm1640: din_gpio_deinit is null.\n");         /* din_gpio_deinit is null */
        
        return 3;                                                          /* return error */
    }
    if (handle->din_gpio_write == NULL)                                    /* check din_gpio_write */
    {
        handle->debug_print("tm1640: din_gpio_write is null.\n");          /* din_gpio_write is null */
        
        return 3;                                                          /* return error */
    }
    if (handle->delay_us == NULL)                                          /* check delay_us */
    {
        handle->debug_print("tm1640: delay_us is null.\n");                /* delay_us is null */
        
        return 3;                                                          /* return error */
    }
    if (handle->delay_ms == NULL)                                          /* check delay_ms */
    {
        handle->debug_print("tm1640: delay_ms is null.\n");                /* delay_ms is null */
        
        return 3;                                                          /* return error */
    }
    
    res = handle->sclk_gpio_init();                                        /* sclk gpio init */
    if (res != 0)                                                          /* check result */
    {
        handle->debug_print("tm1640: sclk gpio init failed.\n");           /* sclk gpio init failed */
        
        return 1;                                                          /* return error */
    }
    res = handle->din_gpio_init();                                         /* din gpio init */
    if (res != 0)                                                          /* check result */
    {
        handle->debug_print("tm1640: din gpio init failed.\n");            /* din gpio init failed */
        (void)handle->sclk_gpio_deinit();                                  /* sclk gpio deinit */
        
        return 1;                                                          /* return error */
    }
    res = handle->sclk_gpio_write(1);                                      /* set high */
    if (res != 0)                                                          /* check result */
    {
        handle->debug_print("tm1640: sclk gpio write failed.\n");          /* sclk gpio write failed */
        (void)handle->sclk_gpio_deinit();                                  /* sclk gpio deinit */
        (void)handle->din_gpio_deinit();                                   /* din gpio deinit */
        
        return 1;                                                          /* return error */
    }
    res = handle->din_gpio_write(1);                                       /* set high */
    if (res != 0)                                                          /* check result */
    {
        handle->debug_print("tm1640: din gpio write failed.\n");           /* din gpio write failed */
        (void)handle->sclk_gpio_deinit();                                  /* sclk gpio deinit */
        (void)handle->din_gpio_deinit();                                   /* din gpio deinit */
        
        return 1;                                                          /* return error */
    }
    handle->data_conf = 0x00;                                              /* init 0 */
    handle->display_conf = 0x00;                                           /* init 0 */
    cmd = TM1640_COMMAND_DISPLAY | handle->display_conf;                   /* set the command */
    res = a_tm1640_write(handle, cmd, NULL, 0);                            /* write */
    if (res != 0)                                                          /* check error */
    {
        handle->debug_print("tm1640: write failed.\n");                    /* write failed */
        (void)handle->sclk_gpio_deinit();                                  /* sclk gpio deinit */
        (void)handle->din_gpio_deinit();                                   /* din gpio deinit */
        
        return 1;                                                          /* return error */
    }
    handle->inited = 1;                                                    /* flag inited */
    
    return 0;                                                              /* success return 0 */
}

/**
 * @brief     close the chip
 * @param[in] *handle pointer to a tm1640 handle structure
 * @return    status code
 *            - 0 success
 *            - 1 gpio deinit failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 *            - 4 power down failed
 * @note      none
 */
uint8_t tm1640_deinit(tm1640_handle_t *handle)
{
    uint8_t res;
    uint8_t cmd;
    
    if (handle == NULL)                                                   /* check handle */
    {
        return 2;                                                         /* return error */
    }
    if (handle->inited != 1)                                              /* check handle initialization */
    {
        return 3;                                                         /* return error */
    }
    
    handle->display_conf &= ~(1 << 3);                                    /* clear settings */
    cmd = TM1640_COMMAND_DISPLAY | handle->display_conf;                  /* set the command */
    res = a_tm1640_write(handle, cmd, NULL, 0);                           /* write */
    if (res != 0)                                                         /* check error */
    {
        handle->debug_print("tm1640: write failed.\n");                   /* write failed */
        
        return 4;                                                         /* return error */
    }
    
    res = handle->sclk_gpio_deinit();                                     /* sclk gpio deinit */
    if (res != 0)                                                         /* check the result */
    {
        handle->debug_print("tm1640: sclk gpio deinit failed.\n");        /* sclk gpio deinit failed */
        
        return 1;                                                         /* return error */
    }
    res = handle->din_gpio_deinit();                                      /* din gpio deinit */
    if (res != 0)                                                         /* check the result */
    {
        handle->debug_print("tm1640: din gpio deinit failed.\n");         /* din gpio deinit failed */
        
        return 1;                                                         /* return error */
    }
    handle->inited = 0;                                                   /* flag close */
    
    return 0;                                                             /* success return 0 */
}

/**
 * @brief     set pulse width
 * @param[in] *handle pointer to a tm1640 handle structure
 * @param[in] width pulse width
 * @return    status code
 *            - 0 success
 *            - 1 set pulse width failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t tm1640_set_pulse_width(tm1640_handle_t *handle, tm1640_pulse_width_t width)
{
    uint8_t res;
    uint8_t cmd;
    
    if (handle == NULL)                                         /* check handle */
    {
        return 2;                                               /* return error */
    }
    if (handle->inited != 1)                                    /* check handle initialization */
    {
        return 3;                                               /* return error */
    }
    
    handle->display_conf &= ~(7 << 0);                          /* clear settings */
    handle->display_conf |= width;                              /* set display conf */
    cmd = TM1640_COMMAND_DISPLAY | handle->display_conf;        /* set the command */
    res = a_tm1640_write(handle, cmd, NULL, 0);                 /* write */
    if (res != 0)                                               /* check error */
    {
        handle->debug_print("tm1640: write failed.\n");         /* write failed */
        
        return 1;                                               /* return error */
    }
    
    return 0;                                                   /* success return 0 */
}

/**
 * @brief      get pulse width
 * @param[in]  *handle pointer to a tm1640 handle structure
 * @param[out] *width pointer to a pulse width buffer
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t tm1640_get_pulse_width(tm1640_handle_t *handle, tm1640_pulse_width_t *width)
{
    if (handle == NULL)                                                 /* check handle */
    {
        return 2;                                                       /* return error */
    }
    if (handle->inited != 1)                                            /* check handle initialization */
    {
        return 3;                                                       /* return error */
    }
    
    *width = (tm1640_pulse_width_t)(handle->display_conf & 0x7);        /* get width */
    
    return 0;                                                           /* success return 0 */
}

/**
 * @brief     enable or disable display
 * @param[in] *handle pointer to a tm1640 handle structure
 * @param[in] enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 set display failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t tm1640_set_display(tm1640_handle_t *handle, tm1640_bool_t enable)
{
    uint8_t res;
    uint8_t cmd;
    
    if (handle == NULL)                                         /* check handle */
    {
        return 2;                                               /* return error */
    }
    if (handle->inited != 1)                                    /* check handle initialization */
    {
        return 3;                                               /* return error */
    }
    
    handle->display_conf &= ~(1 << 3);                          /* clear settings */
    handle->display_conf |= enable << 3;                        /* set display conf */
    cmd = TM1640_COMMAND_DISPLAY | handle->display_conf;        /* set the command */
    res = a_tm1640_write(handle, cmd, NULL, 0);                 /* write */
    if (res != 0)                                               /* check error */
    {
        handle->debug_print("tm1640: write failed.\n");         /* write failed */
        
        return 1;                                               /* return error */
    }
    
    return 0;                                                   /* success return 0 */
}

/**
 * @brief      get display status
 * @param[in]  *handle pointer to a tm1640 handle structure
 * @param[out] *enable pointer to a bool value buffer
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t tm1640_get_display(tm1640_handle_t *handle, tm1640_bool_t *enable)
{
    if (handle == NULL)                                                 /* check handle */
    {
        return 2;                                                       /* return error */
    }
    if (handle->inited != 1)                                            /* check handle initialization */
    {
        return 3;                                                       /* return error */
    }
    
    *enable = (tm1640_bool_t)((handle->display_conf >> 3) & 0x01);      /* get bool */
    
    return 0;                                                           /* success return 0 */
}

/**
 * @brief     set address mode
 * @param[in] *handle pointer to a tm1640 handle structure
 * @param[in] mode address mode
 * @return    status code
 *            - 0 success
 *            - 1 set address mode failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t tm1640_set_address_mode(tm1640_handle_t *handle, tm1640_address_mode_t mode)
{
    uint8_t res;
    uint8_t cmd;
    
    if (handle == NULL)                                         /* check handle */
    {
        return 2;                                               /* return error */
    }
    if (handle->inited != 1)                                    /* check handle initialization */
    {
        return 3;                                               /* return error */
    }
    
    handle->data_conf &= ~(1 << 2);                             /* clear settings */
    handle->data_conf |= mode << 2;                             /* set address mode */
    cmd = TM1640_COMMAND_DATA | handle->data_conf;              /* set the command */
    res = a_tm1640_write(handle, cmd, NULL, 0);                 /* write */
    if (res != 0)                                               /* check error */
    {
        handle->debug_print("tm1640: write failed.\n");         /* write failed */
        
        return 1;                                               /* return error */
    }
    
    return 0;                                                   /* success return 0 */
}

/**
 * @brief      get address mode
 * @param[in]  *handle pointer to a tm1640 handle structure
 * @param[out] *mode pointer to an address mode buffer
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t tm1640_get_address_mode(tm1640_handle_t *handle, tm1640_address_mode_t *mode)
{
    if (handle == NULL)                                                      /* check handle */
    {
        return 2;                                                            /* return error */
    }
    if (handle->inited != 1)                                                 /* check handle initialization */
    {
        return 3;                                                            /* return error */
    }
    
    *mode = (tm1640_address_mode_t)((handle->data_conf >> 2) & 0x01);        /* get address mode */
    
    return 0;                                                                /* success return 0 */
}

/**
 * @brief     enable or disable test mode
 * @param[in] *handle pointer to a tm1640 handle structure
 * @param[in] enable bool value
 * @return    status code
 *            - 0 success
 *            - 1 set test mode failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t tm1640_set_test_mode(tm1640_handle_t *handle, tm1640_bool_t enable)
{
    uint8_t res;
    uint8_t cmd;
    
    if (handle == NULL)                                         /* check handle */
    {
        return 2;                                               /* return error */
    }
    if (handle->inited != 1)                                    /* check handle initialization */
    {
        return 3;                                               /* return error */
    }
    
    handle->data_conf &= ~(1 << 3);                             /* clear settings */
    handle->data_conf |= enable << 3;                           /* set test mode */
    cmd = TM1640_COMMAND_DATA | handle->data_conf;              /* set the command */
    res = a_tm1640_write(handle, cmd, NULL, 0);                 /* write */
    if (res != 0)                                               /* check error */
    {
        handle->debug_print("tm1640: write failed.\n");         /* write failed */
        
        return 1;                                               /* return error */
    }
    
    return 0;                                                   /* success return 0 */
}

/**
 * @brief      get test mode status
 * @param[in]  *handle pointer to a tm1640 handle structure
 * @param[out] *enable pointer to a bool value buffer
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 *             - 3 handle is not initialized
 * @note       none
 */
uint8_t tm1640_get_test_mode(tm1640_handle_t *handle, tm1640_bool_t *enable)
{
    if (handle == NULL)                                                /* check handle */
    {
        return 2;                                                      /* return error */
    }
    if (handle->inited != 1)                                           /* check handle initialization */
    {
        return 3;                                                      /* return error */
    }
    
    *enable = (tm1640_bool_t)((handle->data_conf >> 3) & 0x01);        /* get test mode */
    
    return 0;                                                          /* success return 0 */
}

/**
 * @brief     clear segment
 * @param[in] *handle pointer to a tm1640 handle structure
 * @return    status code
 *            - 0 success
 *            - 1 clear segment failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t tm1640_clear_segment(tm1640_handle_t *handle)
{
    uint8_t res;
    uint8_t i;
    uint8_t cmd;
    uint8_t data[16] = {0};
    
    if (handle == NULL)                                                 /* check handle */
    {
        return 2;                                                       /* return error */
    }
    if (handle->inited != 1)                                            /* check handle initialization */
    {
        return 3;                                                       /* return error */
    }
    
    cmd = TM1640_COMMAND_DATA | handle->data_conf;                      /* set the command */
    res = a_tm1640_write(handle, cmd, NULL, 0);                         /* write */
    if (res != 0)                                                       /* check error */
    {
        handle->debug_print("tm1640: write failed.\n");                 /* write failed */
        
        return 1;                                                       /* return error */
    }

    if ((handle->data_conf & (1 << 2)) != 0)                            /* fixed address mode */
    {
        for (i = 0; i < 16; i++)                                        /* loop all */
        {
            uint8_t temp;
            
            cmd = TM1640_COMMAND_ADDRESS | i;                           /* set the command */
            temp = data[i];                                             /* set lsb */
            res = a_tm1640_write(handle, cmd, &temp, 1);                /* write */
            if (res != 0)                                               /* check error */
            {
                handle->debug_print("tm1640: write failed.\n");         /* write failed */
                
                return 1;                                               /* return error */
            }
        }
    }
    else                                                                /* auto increment 1 mode */
    {
        cmd = TM1640_COMMAND_ADDRESS;                                   /* set the command */
        res = a_tm1640_write(handle, cmd, data, 16);                    /* write */
        if (res != 0)                                                   /* check error */
        {
            handle->debug_print("tm1640: write failed.\n");             /* write failed */
            
            return 1;                                                   /* return error */
        }
    }
    
    return 0;                                                           /* success return 0 */
}

/**
 * @brief     write segment
 * @param[in] *handle pointer to a tm1640 handle structure
 * @param[in] addr start address
 * @param[in] *data pointer to a data buffer
 * @param[in] len data length
 * @return    status code
 *            - 0 success
 *            - 1 write segment failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 *            - 4 addr + len > 16
 * @note      none
 */
uint8_t tm1640_write_segment(tm1640_handle_t *handle, uint8_t addr, uint8_t *data, uint8_t len)
{
    uint8_t res;
    uint8_t i;
    uint8_t cmd;
    
    if (handle == NULL)                                                 /* check handle */
    {
        return 2;                                                       /* return error */
    }
    if (handle->inited != 1)                                            /* check handle initialization */
    {
        return 3;                                                       /* return error */
    }
    if (addr + len > 16)                                                /* check range */
    {
        handle->debug_print("tm1640: addr + len > 16.\n");              /* addr + len > 16 */
        
        return 4;                                                       /* return error */
    }
    
    cmd = TM1640_COMMAND_DATA | handle->data_conf;                      /* set the command */
    res = a_tm1640_write(handle, cmd, NULL, 0);                         /* write */
    if (res != 0)                                                       /* check error */
    {
        handle->debug_print("tm1640: write failed.\n");                 /* write failed */
        
        return 1;                                                       /* return error */
    }

    if ((handle->data_conf & (1 << 2)) != 0)                            /* fixed address mode */
    {
        for (i = 0; i < len; i++)                                       /* loop all */
        {
            uint8_t temp;
            
            cmd = TM1640_COMMAND_ADDRESS | (addr + i);                  /* set the command */
            temp = data[i];                                             /* set data */
            res = a_tm1640_write(handle, cmd, &temp, 1);                /* write */
            if (res != 0)                                               /* check error */
            {
                handle->debug_print("tm1640: write failed.\n");         /* write failed */
                
                return 1;                                               /* return error */
            }
        }
    }
    else                                                                /* auto increment 1 mode */
    {
        cmd = TM1640_COMMAND_ADDRESS | addr;                            /* set the command */
        res = a_tm1640_write(handle, cmd, data, len);                   /* write */
        if (res != 0)                                                   /* check error */
        {
            handle->debug_print("tm1640: write failed.\n");             /* write failed */
            
            return 1;                                                   /* return error */
        }
    }
    
    return 0;                                                           /* success return 0 */
}

/**
 * @brief     set the chip register
 * @param[in] *handle pointer to a tm1640 handle structure
 * @param[in] cmd sent command
 * @param[in] *data pointer to a data buffer
 * @param[in] len data buffer length
 * @return    status code
 *            - 0 success
 *            - 1 write failed
 *            - 2 handle is NULL
 *            - 3 handle is not initialized
 * @note      none
 */
uint8_t tm1640_set_reg(tm1640_handle_t *handle, uint8_t cmd, uint8_t *data, uint8_t len)
{
    uint8_t res;
    
    if (handle == NULL)                                             /* check handle */
    {
        return 2;                                                   /* return error */
    }
    if (handle->inited != 1)                                        /* check handle initialization */
    {
        return 3;                                                   /* return error */
    }
    
    res = a_tm1640_write(handle, cmd, data, len);                   /* write */
    if (res != 0)                                                   /* check error */
    {
        handle->debug_print("tm1640: write failed.\n");             /* write failed */
        
        return 1;                                                   /* return error */
    }
    
    return 0;                                                       /* success return 0 */
}

/**
 * @brief      get chip's information
 * @param[out] *info pointer to a tm1640 info structure
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 * @note       none
 */
uint8_t tm1640_info(tm1640_info_t *info)
{
    if (info == NULL)                                               /* check handle */
    {
        return 2;                                                   /* return error */
    }
    
    memset(info, 0, sizeof(tm1640_info_t));                         /* initialize tm1640 info structure */
    strncpy(info->chip_name, CHIP_NAME, 32);                        /* copy chip name */
    strncpy(info->manufacturer_name, MANUFACTURER_NAME, 32);        /* copy manufacturer name */
    strncpy(info->interface, "GPIO", 8);                            /* copy interface name */
    info->supply_voltage_min_v = SUPPLY_VOLTAGE_MIN;                /* set minimal supply voltage */
    info->supply_voltage_max_v = SUPPLY_VOLTAGE_MAX;                /* set maximum supply voltage */
    info->max_current_ma = MAX_CURRENT;                             /* set maximum current */
    info->temperature_max = TEMPERATURE_MAX;                        /* set minimal temperature */
    info->temperature_min = TEMPERATURE_MIN;                        /* set maximum temperature */
    info->driver_version = DRIVER_VERSION;                          /* set driver version */
    
    return 0;                                                       /* success return 0 */
}
