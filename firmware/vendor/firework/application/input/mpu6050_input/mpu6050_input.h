/**
 * @file mpu6050_input.h
 * @brief MPU6050 原始数据、DMP 姿态数据和读取统计的 Application 接口。
 *
 * 传感器读取在后台任务中进行，业务代码通过快照接口获取最近一帧数据。
 */
#ifndef APPLICATION_INPUT_MPU6050_INPUT_H
#define APPLICATION_INPUT_MPU6050_INPUT_H

#include <stdbool.h>
#include <stdint.h>

#include "modules/mpu6050/mpu6050.h"

/** MPU6050 输入任务的运行状态和最新一次读取结果。 */
typedef struct {
    MPU6050Sample sample;
    MPU6050DmpSample dmp_sample;
    uint32_t successful_read_count;
    uint32_t read_error_count;
    bool sample_valid;
    bool dmp_sample_valid;
    bool sensor_initialized;
    bool dmp_enabled;
    bool ready;
} MPU6050InputStatus;

/** 注册、初始化 MPU6050，并创建静态周期读取任务。 */
bool MPU6050InputInit(void);

/** 获取最新一帧换算后的数据；尚未成功读取时返回 false。 */
bool MPU6050InputGetSample(MPU6050Sample *sample);

/** 获取最新一帧 DMP 四元数和姿态角；未启用或尚未成功读取时返回 false。 */
bool MPU6050InputGetDmpSample(MPU6050DmpSample *sample);

/** 获取任务状态、统计计数和最新数据。 */
bool MPU6050InputGetStatus(MPU6050InputStatus *status);

/** 返回 Application 是否已经完成 MPU6050 初始化和任务创建。 */
bool MPU6050InputIsReady(void);

/** 返回 MPU6050 任务启动以来的最小空闲栈，单位为 words。 */
uint32_t MPU6050InputGetMinimumFreeStackWords(void);

#endif
