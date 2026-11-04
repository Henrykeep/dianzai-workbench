/*
 * FreeRTOS V202112.00
 * Copyright (C) 2020 Amazon.com, Inc. or its affiliates.  All Rights Reserved.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy of
 * this software and associated documentation files (the "Software"), to deal in
 * the Software without restriction, including without limitation the rights to
 * use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
 * the Software, and to permit persons to whom the Software is furnished to do so,
 * subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
 * FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
 * COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
 * IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
 * CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 *
 * http://www.FreeRTOS.org
 * http://aws.amazon.com/freertos
 *
 * 1 tab == 4 spaces!
 */

/******************************************************************************
 * Minimal framework entry for MSPM0G3507 + LP-MSPM0G3507.
 *
 * Product initialization and task creation belong to the application layer.
 * This file only enters the framework and provides FreeRTOS hooks.
 *
 * 本文件仅保留系统入口和 FreeRTOS 钩子，具体业务初始化及任务创建由
 * application 层负责，避免 main.c 与具体硬件或业务逻辑耦合。
 */

/* Kernel includes. */
#include "FreeRTOS.h"
#include "task.h"

#include "application/application.h"
#include "bsp/bsp.h"

#include <stdint.h>

/*-----------------------------------------------------------*/

/* 保留最后一次 NMI 原始状态和 ECC 错误地址，便于调试器定位。 */
volatile uint32_t application_nmi_raw_status;
volatile uint32_t application_nmi_error_address;

void ApplicationFatalHalt(void)
{
    BSPEnterSafeState();
    while (1) {
    }
}

/* 覆盖启动文件的 weak fault handler，先执行无锁硬件关断再停机。 */
void NMI_Handler(void)
{
    /* MSPM0G3507 SYSCTL SOCLOCK: NMIRIS=0x400B0060，DEDERRADDR=0x400B020C。 */
    application_nmi_raw_status =
        *((volatile uint32_t *)0x400B0060U);
    application_nmi_error_address =
        *((volatile uint32_t *)0x400B020CU);
    ApplicationFatalHalt();
}

void HardFault_Handler(void)
{
    ApplicationFatalHalt();
}

/*-----------------------------------------------------------*/

int main(void)
{
    /* 先完成板级、模块和应用初始化，全部成功后再启动调度器。 */
    if (ApplicationInit() == FRAMEWORK_STATUS_OK) {
        ApplicationStart();
    }

    ApplicationEnterSafeState();

    /*
     * 正常情况下调度器不会返回；若运行到这里，通常表示初始化失败，
     * 或 FreeRTOS 创建空闲/定时器任务时堆内存不足。
     */
    for (;;) {
    }
}
/*-----------------------------------------------------------*/

#if (configCHECK_FOR_STACK_OVERFLOW)
/*
     *  ======== vApplicationStackOverflowHook ========
     *  When stack overflow checking is enabled the application must provide a
     *  stack overflow hook function. This default hook function is declared as
     *  weak, and will be used by default, unless the application specifically
     *  provides its own hook function.
     */
#if defined(__IAR_SYSTEMS_ICC__)
__weak void vApplicationStackOverflowHook(
    TaskHandle_t pxTask, char *pcTaskName)
#elif (defined(__TI_COMPILER_VERSION__))
#pragma WEAK(vApplicationStackOverflowHook)
void vApplicationStackOverflowHook(TaskHandle_t pxTask, char *pcTaskName)
#elif (defined(__GNUC__) || defined(__ti_version__))
void __attribute__((weak))
vApplicationStackOverflowHook(TaskHandle_t pxTask, char *pcTaskName)
#endif
{
    /* 栈溢出时不能获取 RTOS 互斥锁，只执行 BSP 无锁安全关断。 */
    (void)pxTask;
    (void)pcTaskName;
    ApplicationFatalHalt();
}
#endif

/*-----------------------------------------------------------*/
