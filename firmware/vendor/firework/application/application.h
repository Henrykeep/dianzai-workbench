/**
 * @file application.h
 * @brief Application 层的统一启动、就绪状态和安全停机接口。
 *
 * 本文件只描述启动编排对外暴露的接口；具体功能仍由各业务子模块实现。
 */
#ifndef APPLICATION_H
#define APPLICATION_H

#include <stdbool.h>

typedef enum {
    /* 框架初始化成功，可以安全启动 FreeRTOS 调度器。 */
    FRAMEWORK_STATUS_OK = 0,
    /* 任一模块注册或任务创建失败。 */
    FRAMEWORK_STATUS_ERROR
} Framework_Status_e;

/** 初始化阶段，用于定位最近一次失败发生在哪个 Application。 */
typedef enum {
    APPLICATION_STAGE_NONE = 0,
    APPLICATION_STAGE_BSP,
    APPLICATION_STAGE_SERIAL,
    APPLICATION_STAGE_WAVEFORM_MEASUREMENT,
    APPLICATION_STAGE_ADC_JUSTFLOAT,
    APPLICATION_STAGE_WAVEFORM_OUTPUT,
    APPLICATION_STAGE_ARBITRARY_WAVEFORM,
    APPLICATION_STAGE_PA27_THRESHOLD_TRIGGER,
    APPLICATION_STAGE_WAVEFORM_MAPPING,
    APPLICATION_STAGE_MPU6050_INPUT,
    APPLICATION_STAGE_SERVO_CONTROL,
    APPLICATION_STAGE_TB6612_CONTROL,
    APPLICATION_STAGE_MATRIX_KEYPAD,
    APPLICATION_STAGE_DISPLAY_MENU,
    /* 保留旧枚举名称，新代码请使用 DISPLAY_MENU。 */
    APPLICATION_STAGE_OLED_MENU = APPLICATION_STAGE_DISPLAY_MENU,
    APPLICATION_STAGE_SCHEDULER
} ApplicationStage_e;

/** 启动 FreeRTOS 前，依次初始化 BSP、功能模块和应用。 */
Framework_Status_e ApplicationInit(void);

/** 初始化成功后启动 FreeRTOS 调度器。 */
void ApplicationStart(void);

/** 返回最近一次初始化或启动失败所在阶段。 */
ApplicationStage_e ApplicationGetLastErrorStage(void);

/** 返回应用是否已经完整初始化。 */
bool ApplicationIsReady(void);

/** 立即关闭应用拥有的 DAC、DDS、电机、舵机和通用 PWM 输出。 */
void ApplicationEnterSafeState(void);

#endif
