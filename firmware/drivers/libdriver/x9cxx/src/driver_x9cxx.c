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
 * @file      driver_x9cxx.c
 * @brief     driver x9cxx source file
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

#include "driver_x9cxx.h"

/**
 * @brief chip information definition
 */
#define CHIP_NAME                 "Renesas X9CXX"        /**< chip name */
#define MANUFACTURER_NAME         "Renesas"              /**< manufacturer name */
#define SUPPLY_VOLTAGE_MIN        4.5f                   /**< chip min supply voltage */
#define SUPPLY_VOLTAGE_MAX        5.5f                   /**< chip max supply voltage */
#define MAX_CURRENT               3.0f                   /**< chip max current */
#define TEMPERATURE_MIN           -40.0f                 /**< chip min operating temperature */
#define TEMPERATURE_MAX           85.0f                  /**< chip max operating temperature */
#define DRIVER_VERSION            1000                   /**< driver version */

/**
 * @brief     step prev
 * @param[in] *handle pointer to a x9cxx handle structure
 * @param[in] inc increment or decrement
 * @return    status code
 *            - 0 success
 *            - 1 step failed
 * @note      none
 */
static uint8_t a_x9cxx_step_prev(x9cxx_handle_t *handle, uint8_t inc)
{
    uint8_t res;
    
    res = handle->inc_gpio_write(1);                /* inc set high */
    if (res != 0)                                   /* check the result */
    {
        return 1;                                   /* return error */
    }
    handle->delay_us(X9CXX_OPERATE_DELAY_US);       /* delay */
    
    if (inc != 0)                                   /* up */
    {
        res = handle->up_down_gpio_write(1);        /* set up */
        if (res != 0)                               /* check the result */
        {
            return 1;                               /* return error */
        }
    }
    else                                            /* down */
    {
        res = handle->up_down_gpio_write(0);        /* set down */
        if (res != 0)                               /* check the result */
        {
            return 1;                               /* return error */
        }
    }
    handle->delay_us(X9CXX_OPERATE_DELAY_US);       /* delay */
    
    res = handle->cs_gpio_write(0);                 /* cs set low */
    if (res != 0)                                   /* check the result */
    {
        return 1;                                   /* return error */
    }
    handle->delay_us(X9CXX_OPERATE_DELAY_US);       /* delay */
    
    return 0;                                       /* success return 0 */
}

/**
 * @brief     step
 * @param[in] *handle pointer to a x9cxx handle structure
 * @param[in] inc increment or decrement
 * @return    status code
 *            - 0 success
 *            - 1 step failed
 * @note      none
 */
static uint8_t a_x9cxx_step(x9cxx_handle_t *handle, uint8_t inc)
{
    uint8_t res;
    
    res = handle->inc_gpio_write(1);                /* inc set high */
    if (res != 0)                                   /* check the result */
    {
        return 1;                                   /* return error */
    }
    handle->delay_us(X9CXX_STEP_DELAY_US);          /* delay */
    res = handle->inc_gpio_write(0);                /* inc set low */
    if (res != 0)                                   /* check the result */
    {
        return 1;                                   /* return error */
    }
    handle->delay_us(X9CXX_STEP_DELAY_US);          /* delay */
    
    if (inc != 0)                                   /* up */
    {
        handle->step++;                             /* step++ */
        if (handle->step > 99)                      /* check over 99 */
        {
            handle->step = 99;                      /* set 99 */
        }
    }
    else                                            /* down */
    {
        if (handle->step != 0)                      /* check 0 */
        {
            handle->step--;                         /* step-- */
        }
    }
    
    return 0;                                       /* success return 0 */
}

/**
 * @brief     reset
 * @param[in] *handle pointer to a x9cxx handle structure
 * @param[in] inc increment or decrement
 * @return    status code
 *            - 0 success
 *            - 1 step failed
 * @note      none
 */
static uint8_t a_x9cxx_reset(x9cxx_handle_t *handle, uint8_t inc)
{
    uint8_t res;
    uint8_t i;
    
    res = handle->inc_gpio_write(1);                    /* inc set high */
    if (res != 0)                                       /* check the result */
    {
        return 1;                                       /* return error */
    }
    handle->delay_us(X9CXX_OPERATE_DELAY_US);           /* delay */
    
    if (inc != 0)                                       /* up */
    {
        res = handle->up_down_gpio_write(1);            /* set up */
        if (res != 0)                                   /* check the result */
        {
            return 1;                                   /* return error */
        }
    }
    else                                                /* down */
    {
        res = handle->up_down_gpio_write(0);            /* set down */
        if (res != 0)                                   /* check the result */
        {
            return 1;                                   /* return error */
        }
    }
    handle->delay_us(X9CXX_OPERATE_DELAY_US);           /* delay */
    
    res = handle->cs_gpio_write(0);                     /* cs set low */
    if (res != 0)                                       /* check the result */
    {
        return 1;                                       /* return error */
    }
    handle->delay_us(X9CXX_OPERATE_DELAY_US);           /* delay */
    
    for (i = 0; i < 100; i++)                           /* 100 steps */
    {
        res = handle->inc_gpio_write(1);                /* inc set high */
        if (res != 0)                                   /* check the result */
        {
            return 1;                                   /* return error */
        }
        handle->delay_us(X9CXX_STEP_DELAY_US);          /* delay */
        res = handle->inc_gpio_write(0);                /* inc set low */
        if (res != 0)                                   /* check the result */
        {
            return 1;                                   /* return error */
        }
        handle->delay_us(X9CXX_STEP_DELAY_US);          /* delay */
    }
    
    if (inc != 0)                                       /* up */
    {
        handle->step = 99;                              /* set 99 */
    }
    else                                                /* down */
    {
        handle->step = 0;                               /* set 0 */
    }
    handle->valid = 1;                                  /* set valid */
    
    return 0;                                           /* success return 0 */
}

/**
 * @brief     store
 * @param[in] *handle pointer to a x9cxx handle structure
 * @return    status code
 *            - 0 success
 *            - 1 store failed
 * @note      none
 */
static uint8_t a_x9cxx_store(x9cxx_handle_t *handle)
{
    uint8_t res;
    
    res = handle->inc_gpio_write(1);            /* inc set high */
    if (res != 0)                               /* check the result */
    {
        return 1;                               /* return error */
    }
    handle->delay_us(X9CXX_OPERATE_DELAY_US);   /* delay */
    res = handle->cs_gpio_write(1);             /* cs set high */
    if (res != 0)                               /* check the result */
    {
        return 1;                               /* return error */
    }
    handle->delay_ms(X9CXX_STORE_DELAY_MS);     /* delay */
    
    return 0;                                   /* success return 0 */
}

/**
 * @brief     no store
 * @param[in] *handle pointer to a x9cxx handle structure
 * @return    status code
 *            - 0 success
 *            - 1 store failed
 * @note      none
 */
static uint8_t a_x9cxx_no_store(x9cxx_handle_t *handle)
{
    uint8_t res;
    
    res = handle->inc_gpio_write(0);            /* inc set low */
    if (res != 0)                               /* check the result */
    {
        return 1;                               /* return error */
    }
    handle->delay_us(X9CXX_OPERATE_DELAY_US);   /* delay */
    res = handle->cs_gpio_write(1);             /* cs set high */
    if (res != 0)                               /* check the result */
    {
        return 1;                               /* return error */
    }
    handle->delay_ms(X9CXX_STORE_DELAY_MS);     /* delay */
    
    return 0;                                   /* success return 0 */
}

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
uint8_t x9cxx_init(x9cxx_handle_t *handle)
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
    if (handle->cs_gpio_init == NULL)                                      /* check cs_gpio_init */
    {
        handle->debug_print("x9cxx: cs_gpio_init is null.\n");             /* cs_gpio_init is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->cs_gpio_deinit == NULL)                                    /* check cs_gpio_deinit */
    {
        handle->debug_print("x9cxx: cs_gpio_deinit is null.\n");           /* cs_gpio_deinit is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->cs_gpio_write == NULL)                                     /* check cs_gpio_write */
    {
        handle->debug_print("x9cxx: cs_gpio_write is null.\n");            /* cs_gpio_write is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->up_down_gpio_init == NULL)                                 /* check up_down_gpio_init */
    {
        handle->debug_print("x9cxx: up_down_gpio_init is null.\n");        /* up_down_gpio_init is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->up_down_gpio_deinit == NULL)                               /* check up_down_gpio_deinit */
    {
        handle->debug_print("x9cxx: up_down_gpio_deinit is null.\n");      /* up_down_gpio_deinit is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->up_down_gpio_write == NULL)                                /* check up_down_gpio_write */
    {
        handle->debug_print("x9cxx: up_down_gpio_write is null.\n");       /* up_down_gpio_write is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->inc_gpio_init == NULL)                                     /* check inc_gpio_init */
    {
        handle->debug_print("x9cxx: inc_gpio_init is null.\n");            /* inc_gpio_init is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->inc_gpio_deinit == NULL)                                   /* check inc_gpio_deinit */
    {
        handle->debug_print("x9cxx: inc_gpio_deinit is null.\n");          /* inc_gpio_deinit is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->inc_gpio_write == NULL)                                    /* check inc_gpio_write */
    {
        handle->debug_print("x9cxx: inc_gpio_write is null.\n");           /* inc_gpio_write is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->delay_ms == NULL)                                          /* check delay_ms */
    {
        handle->debug_print("x9cxx: delay_ms is null.\n");                 /* delay_ms is null */
       
        return 3;                                                          /* return error */
    }
    if (handle->delay_us == NULL)                                          /* check delay_us */
    {
        handle->debug_print("x9cxx: delay_us is null.\n");                 /* delay_us is null */
       
        return 3;                                                          /* return error */
    }
    
    if (handle->cs_gpio_init() != 0)                                       /* cs gpio init */
    {
        handle->debug_print("x9cxx: cs gpio init failed.\n");              /* cs gpio init failed */
       
        return 1;                                                          /* return error */
    }
    if (handle->up_down_gpio_init() != 0)                                  /* up down gpio init */
    {
        handle->debug_print("x9cxx: up down gpio init failed.\n");         /* up down gpio init failed */
        (void)handle->cs_gpio_deinit();                                    /* cs gpio deinit */
       
        return 1;                                                          /* return error */
    }
    if (handle->inc_gpio_init() != 0)                                      /* inc gpio init */
    {
        handle->debug_print("x9cxx: inc gpio init failed.\n");             /* inc gpio init failed */
        (void)handle->cs_gpio_deinit();                                    /* cs gpio deinit */
        (void)handle->up_down_gpio_deinit();                               /* up down gpio deinit */
       
        return 1;                                                          /* return error */
    }
    res = handle->up_down_gpio_write(1);                                   /* up down set high */
    if (res != 0)                                                          /* check the result */
    {
        handle->debug_print("x9cxx: up down gpio write failed.\n");        /* up down gpio write failed */
        (void)handle->cs_gpio_deinit();                                    /* cs gpio deinit */
        (void)handle->up_down_gpio_deinit();                               /* up down gpio deinit */
        (void)handle->inc_gpio_deinit();                                   /* inc gpio deinit */
        
        return 1;                                                          /* return error */
    }
    res = handle->inc_gpio_write(1);                                       /* inc set high */
    if (res != 0)                                                          /* check the result */
    {
        handle->debug_print("x9cxx: inc gpio write failed.\n");            /* inc gpio write failed */
        (void)handle->cs_gpio_deinit();                                    /* cs gpio deinit */
        (void)handle->up_down_gpio_deinit();                               /* up down gpio deinit */
        (void)handle->inc_gpio_deinit();                                   /* inc gpio deinit */
        
        return 1;                                                          /* return error */
    }
    res = handle->cs_gpio_write(1);                                        /* cs set high */
    if (res != 0)                                                          /* check the result */
    {
        handle->debug_print("x9cxx: cs gpio write failed.\n");             /* cs gpio write failed */
        (void)handle->cs_gpio_deinit();                                    /* cs gpio deinit */
        (void)handle->up_down_gpio_deinit();                               /* up down gpio deinit */
        (void)handle->inc_gpio_deinit();                                   /* inc gpio deinit */
        
        return 1;                                                          /* return error */
    }
    handle->step = 0;                                                      /* init 0 */
    handle->valid = 0;                                                     /* set invalid */
    handle->inited = 1;                                                    /* flag initialization */
    
    return 0;                                                              /* success return 0 */
}

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
uint8_t x9cxx_deinit(x9cxx_handle_t *handle)
{
    if (handle == NULL)                                                      /* check handle */
    {
        return 2;                                                            /* return error */
    }
    if (handle->inited != 1)                                                 /* check handle initialization */
    {
        return 3;                                                            /* return error */
    }
    
    if (handle->cs_gpio_deinit() != 0)                                       /* cs gpio deinit */
    {
        handle->debug_print("x9cxx: cs gpio deinit failed.\n");              /* cs gpio deinit failed */
       
        return 1;                                                            /* return error */
    }
    if (handle->up_down_gpio_deinit() != 0)                                  /* up down gpio deinit */
    {
        handle->debug_print("x9cxx: up down gpio deinit failed.\n");         /* up down gpio deinit failed */
       
        return 1;                                                            /* return error */
    }
    if (handle->inc_gpio_deinit() != 0)                                      /* inc gpio deinit */
    {
        handle->debug_print("x9cxx: inc gpio deinit failed.\n");             /* inc gpio deinit failed */
       
        return 1;                                                            /* return error */
    }
    handle->inited = 0;                                                      /* flag closed */
    
    return 0;                                                                /* success return 0 */
}

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
uint8_t x9cxx_reset_to_min(x9cxx_handle_t *handle, x9cxx_bool_t store_enable)
{
    uint8_t res;
    
    if (handle == NULL)                                           /* check handle */
    {
        return 2;                                                 /* return error */
    }
    if (handle->inited != 1)                                      /* check handle initialization */
    {
        return 3;                                                 /* return error */
    }
    
    res = a_x9cxx_reset(handle, 0);                               /* reset */
    if (res != 0)                                                 /* check the result */
    {
        handle->debug_print("x9cxx: reset failed.\n");            /* reset failed */
        
        return 1;                                                 /* return error */
    }
    
    if (store_enable != X9CXX_BOOL_FALSE)                         /* store */
    {
        res = a_x9cxx_store(handle);                              /* store */
        if (res != 0)                                             /* check the result */
        {
            handle->debug_print("x9cxx: store failed.\n");        /* store failed */
            
            return 1;                                             /* return error */
        }
    }
    else                                                          /* no store */
    {
        res = a_x9cxx_no_store(handle);                           /* no store */
        if (res != 0)                                             /* check the result */
        {
            handle->debug_print("x9cxx: no store failed.\n");     /* no store failed */
            
            return 1;                                             /* return error */
        }
    }
    
    return 0;                                                     /* success return 0 */
}

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
uint8_t x9cxx_reset_to_max(x9cxx_handle_t *handle, x9cxx_bool_t store_enable)
{
    uint8_t res;
    
    if (handle == NULL)                                           /* check handle */
    {
        return 2;                                                 /* return error */
    }
    if (handle->inited != 1)                                      /* check handle initialization */
    {
        return 3;                                                 /* return error */
    }
    
    res = a_x9cxx_reset(handle, 1);                               /* reset */
    if (res != 0)                                                 /* check the result */
    {
        handle->debug_print("x9cxx: reset failed.\n");            /* reset failed */
        
        return 1;                                                 /* return error */
    }
    
    if (store_enable != X9CXX_BOOL_FALSE)                         /* store */
    {
        res = a_x9cxx_store(handle);                              /* store */
        if (res != 0)                                             /* check the result */
        {
            handle->debug_print("x9cxx: store failed.\n");        /* store failed */
            
            return 1;                                             /* return error */
        }
    }
    else                                                          /* no store */
    {
        res = a_x9cxx_no_store(handle);                           /* no store */
        if (res != 0)                                             /* check the result */
        {
            handle->debug_print("x9cxx: no store failed.\n");     /* no store failed */
            
            return 1;                                             /* return error */
        }
    }
    
    return 0;                                                     /* success return 0 */
}

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
uint8_t x9cxx_increment(x9cxx_handle_t *handle, uint8_t step, x9cxx_bool_t store_enable)
{
    uint8_t res;
    uint8_t i;
    
    if (handle == NULL)                                           /* check handle */
    {
        return 2;                                                 /* return error */
    }
    if (handle->inited != 1)                                      /* check handle initialization */
    {
        return 3;                                                 /* return error */
    }
    if (step == 0)                                                /* if 0 */
    {
        return 0;                                                 /* success return 0 */
    }
    
    res = a_x9cxx_step_prev(handle, 1);                           /* step prev */
    if (res != 0)                                                 /* check the result */
    {
        handle->debug_print("x9cxx: step prev failed.\n");        /* step prev failed */
        
        return 1;                                                 /* return error */
    }
    for (i = 0; i < step; i++)                                    /* run step */
    {
        res = a_x9cxx_step(handle, 1);                            /* step */
        if (res != 0)                                             /* check the result */
        {
            handle->debug_print("x9cxx: step failed.\n");         /* step failed */
            
            return 1;                                             /* return error */
        }
    }
    
    if (store_enable != X9CXX_BOOL_FALSE)                         /* store */
    {
        res = a_x9cxx_store(handle);                              /* store */
        if (res != 0)                                             /* check the result */
        {
            handle->debug_print("x9cxx: store failed.\n");        /* store failed */
            
            return 1;                                             /* return error */
        }
    }
    else                                                          /* no store */
    {
        res = a_x9cxx_no_store(handle);                           /* no store */
        if (res != 0)                                             /* check the result */
        {
            handle->debug_print("x9cxx: no store failed.\n");     /* no store failed */
            
            return 1;                                             /* return error */
        }
    }
    
    return 0;                                                     /* success return 0 */
}

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
uint8_t x9cxx_decrement(x9cxx_handle_t *handle, uint8_t step, x9cxx_bool_t store_enable)
{
    uint8_t res;
    uint8_t i;
    
    if (handle == NULL)                                           /* check handle */
    {
        return 2;                                                 /* return error */
    }
    if (handle->inited != 1)                                      /* check handle initialization */
    {
        return 3;                                                 /* return error */
    }
    if (step == 0)                                                /* if 0 */
    {
        return 0;                                                 /* success return 0 */
    }
    
    res = a_x9cxx_step_prev(handle, 0);                           /* step prev */
    if (res != 0)                                                 /* check the result */
    {
        handle->debug_print("x9cxx: step prev failed.\n");        /* step prev failed */
        
        return 1;                                                 /* return error */
    }
    for (i = 0; i < step; i++)                                    /* run step */
    {
        res = a_x9cxx_step(handle, 0);                            /* step */
        if (res != 0)                                             /* check the result */
        {
            handle->debug_print("x9cxx: step failed.\n");         /* step failed */
            
            return 1;                                             /* return error */
        }
    }
    
    if (store_enable != X9CXX_BOOL_FALSE)                         /* store */
    {
        res = a_x9cxx_store(handle);                              /* store */
        if (res != 0)                                             /* check the result */
        {
            handle->debug_print("x9cxx: store failed.\n");        /* store failed */
            
            return 1;                                             /* return error */
        }
    }
    else                                                          /* no store */
    {
        res = a_x9cxx_no_store(handle);                           /* no store */
        if (res != 0)                                             /* check the result */
        {
            handle->debug_print("x9cxx: no store failed.\n");     /* no store failed */
            
            return 1;                                             /* return error */
        }
    }
    
    return 0;                                                     /* success return 0 */
}

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
uint8_t x9cxx_get_step_counter(x9cxx_handle_t *handle, uint8_t *counter)
{
    if (handle == NULL)                                                  /* check handle */
    {
        return 2;                                                        /* return error */
    }
    if (handle->inited != 1)                                             /* check handle initialization */
    {
        return 3;                                                        /* return error */
    }
    if (handle->valid == 0)                                              /* check valid flag */
    {
        handle->debug_print("x9cxx: step counter is invalid.\n");        /* step counter is invalid */
        
        return 1;                                                        /* return error */
    }
    
    *counter = handle->step;                                             /* set step counter */
    
    return 0;                                                            /* success return 0 */
}

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
uint8_t x9cxx_set_absolute_step_counter(x9cxx_handle_t *handle, uint8_t counter, x9cxx_bool_t store_enable)
{
    uint8_t res;
    
    if (handle == NULL)                                                  /* check handle */
    {
        return 2;                                                        /* return error */
    }
    if (handle->inited != 1)                                             /* check handle initialization */
    {
        return 3;                                                        /* return error */
    }
    if (handle->valid == 0)                                              /* check valid flag */
    {
        handle->debug_print("x9cxx: step counter is invalid.\n");        /* step counter is invalid */
        
        return 4;                                                        /* return error */
    }
    if (counter > 99)                                                    /* check counter */
    {
        handle->debug_print("x9cxx: counter > 99.\n");                   /* counter > 100 */
        
        return 5;                                                        /* return error */
    }
    if (counter == handle->step)                                         /* check counter */
    {
        return 0;                                                        /* success return 0 */
    }
    
    if (counter < handle->step)                                          /* decrement */
    {
        res = a_x9cxx_step_prev(handle, 0);                              /* step prev */
        if (res != 0)                                                    /* check the result */
        {
            handle->debug_print("x9cxx: step prev failed.\n");           /* step prev failed */
            
            return 1;                                                    /* return error */
        }
        while (counter < handle->step)                                   /* loop */
        {
            res = a_x9cxx_step(handle, 0);                               /* step */
            if (res != 0)                                                /* check the result */
            {
                handle->debug_print("x9cxx: step failed.\n");            /* step failed */
                
                return 1;                                                /* return error */
            }
        }
    }
    else                                                                 /* increment */
    {
        res = a_x9cxx_step_prev(handle, 1);                              /* step prev */
        if (res != 0)                                                    /* check the result */
        {
            handle->debug_print("x9cxx: step prev failed.\n");           /* step prev failed */
            
            return 1;                                                    /* return error */
        }
        while (counter > handle->step)                                   /* loop */
        {
            res = a_x9cxx_step(handle, 1);                               /* step */
            if (res != 0)                                                /* check the result */
            {
                handle->debug_print("x9cxx: step failed.\n");            /* step failed */
                
                return 1;                                                /* return error */
            }
        }
    }
    
    if (store_enable != X9CXX_BOOL_FALSE)                                /* store */
    {
        res = a_x9cxx_store(handle);                                     /* store */
        if (res != 0)                                                    /* check the result */
        {
            handle->debug_print("x9cxx: store failed.\n");               /* store failed */
            
            return 1;                                                    /* return error */
        }
    }
    else                                                                 /* no store */
    {
        res = a_x9cxx_no_store(handle);                                  /* no store */
        if (res != 0)                                                    /* check the result */
        {
            handle->debug_print("x9cxx: no store failed.\n");            /* no store failed */
            
            return 1;                                                    /* return error */
        }
    }
    
    return 0;                                                            /* success return 0 */
}

/**
 * @brief     set chip type
 * @param[in] *handle pointer to a x9cxx handle structure
 * @param[in] type chip type
 * @return    status code
 *            - 0 success
 *            - 2 handle is NULL
 * @note      none
 */
uint8_t x9cxx_set_type(x9cxx_handle_t *handle, x9cxx_type_t type)
{
    if (handle == NULL)                   /* check handle */
    {
        return 2;                         /* return error */
    }
    
    handle->type = (uint32_t)type;        /* set type */
    
    return 0;                             /* success return 0 */
}

/**
 * @brief      get chip type
 * @param[in]  *handle pointer to a x9cxx handle structure
 * @param[out] *type pointer to a chip type buffer
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 * @note       none
 */
uint8_t x9cxx_get_type(x9cxx_handle_t *handle, x9cxx_type_t *type)
{
    if (handle == NULL)                          /* check handle */
    {
        return 2;                                /* return error */
    }
    
    *type = (x9cxx_type_t)(handle->type);        /* set type */
    
    return 0;                                    /* success return 0 */
}

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
uint8_t x9cxx_resistor_convert_to_register(x9cxx_handle_t *handle, float ohm, uint8_t *step)
{
    if (handle == NULL)                                               /* check handle */
    {
        return 2;                                                     /* return error */
    }
    if (handle->inited != 1)                                          /* check handle initialization */
    {
        return 3;                                                     /* return error */
    }
    
    *step = (uint8_t)(ohm / ((float)(handle->type) / 99.0f));         /* convert real data to register data */
    
    return 0;                                                         /* success return 0 */
}

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
uint8_t x9cxx_resistor_convert_to_data(x9cxx_handle_t *handle, uint8_t step, float *ohm)
{
    if (handle == NULL)                                             /* check handle */
    {
        return 2;                                                   /* return error */
    }
    if (handle->inited != 1)                                        /* check handle initialization */
    {
        return 3;                                                   /* return error */
    }
    
    *ohm = (float)(step) * ((float)(handle->type) / 99.0f);         /* convert raw data to real data */
    
    return 0;                                                       /* success return 0 */
}

/**
 * @brief      get chip's information
 * @param[out] *info pointer to a x9cxx info structure
 * @return     status code
 *             - 0 success
 *             - 2 handle is NULL
 * @note       none
 */
uint8_t x9cxx_info(x9cxx_info_t *info)
{
    if (info == NULL)                                               /* check handle */
    {
        return 2;                                                   /* return error */
    }
    
    memset(info, 0, sizeof(x9cxx_info_t));                          /* initialize x9cxx info structure */
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
