/**
 * @file task_manager.h
 * @brief Application 层静态任务资源的统一创建和查询接口。
 *
 * 任务编号、栈空间和 TCB 由 Task Manager 集中管理，业务模块不直接分配任务资源。
 */
#ifndef APPLICATION_TASK_TASK_MANAGER_H
#define APPLICATION_TASK_TASK_MANAGER_H

#include "FreeRTOS.h"
#include "task.h"

/*
 * Application 层任务的唯一编号。
 * 该编号同时作为 task_manager.c 中任务配置表的索引，新增任务时必须放在
 * APPLICATION_TASK_COUNT 之前，并补充对应的静态资源和配置项。
 */
typedef enum {
    /* UART1～UART3 接收任务由串口 Application 按编译开关选择创建。 */
    APPLICATION_TASK_SERIAL_UART1_RX = 0,
    APPLICATION_TASK_SERIAL_UART2_RX,
    APPLICATION_TASK_SERIAL_UART3_RX,

    /* ADC 采样数据通过 UART2 发送给 VOFA+ 的 JustFloat 任务。 */
    APPLICATION_TASK_ADC_JUSTFLOAT,

    /* 舵机平滑移动控制任务。 */
    APPLICATION_TASK_SERVO_CONTROL,

    /* 通用电机控制 Application 的双路平滑调速任务。 */
    APPLICATION_TASK_MOTOR_CONTROL,
    /* 兼容旧调用方；新代码使用 APPLICATION_TASK_MOTOR_CONTROL。 */
    APPLICATION_TASK_TB6612_CONTROL = APPLICATION_TASK_MOTOR_CONTROL,

    /* 4×4 矩阵键盘固定周期扫描和事件发布任务。 */
    APPLICATION_TASK_MATRIX_KEYPAD,

    /* MPU6050 加速度、温度和陀螺仪周期读取任务。 */
    APPLICATION_TASK_MPU6050_INPUT,

    /* PA27 振幅阈值触发采集并保存到 Flash 槽位的任务。 */
    APPLICATION_TASK_PA27_THRESHOLD_TRIGGER,

    /* 波形参数测量任务和当前显示菜单的轮询任务。 */
    APPLICATION_TASK_WAVEFORM_MEASUREMENT,

    /* DAC DMA 完成后在任务上下文生成下一块固定速率波形数据。 */
    APPLICATION_TASK_DAC_REFILL,

    APPLICATION_TASK_DISPLAY_MENU,
    /* 兼容旧调用方，新代码使用 APPLICATION_TASK_DISPLAY_MENU。 */
    APPLICATION_TASK_OLED_MENU = APPLICATION_TASK_DISPLAY_MENU,

    /* 仅作为任务数量和范围检查的哨兵值，不能用于创建任务。 */
    APPLICATION_TASK_COUNT
} ApplicationTask_e;

/*
 * 使用 Task Manager 中统一分配的静态 TCB 和栈创建 Application 层任务。
 * 同一 task 重复调用时返回首次创建得到的句柄。
 *
 * task_function：对应功能模块提供的任务入口函数，任务入口不能正常返回。
 * argument：原样传递给任务入口，可为 NULL；其生命周期必须覆盖任务运行期。
 * 返回值：创建成功或任务已存在时返回句柄，参数/配置无效或创建失败时返回 NULL。
 */
TaskHandle_t ApplicationTaskCreate(ApplicationTask_e task,
    TaskFunction_t task_function, void *argument);

/* 只查询已经创建的任务句柄，不会创建任务。无效编号返回 NULL。 */
TaskHandle_t ApplicationTaskGetHandle(ApplicationTask_e task);

/*
 * 返回任务启动以来从未使用过的最小栈空间，单位为 StackType_t words。
 * 任务未创建、编号无效或栈资源未启用时返回 0。
 */
uint32_t ApplicationTaskGetMinimumFreeStackWords(ApplicationTask_e task);

#endif
