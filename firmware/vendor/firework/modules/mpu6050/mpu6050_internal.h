/**
 * @file mpu6050_internal.h
 * @brief MPU6050 基础寄存器路径与 DMP 适配层共享的私有状态和定点换算接口。
 */
#ifndef MPU6050_INTERNAL_H
#define MPU6050_INTERNAL_H

#include <stddef.h>
#include <stdint.h>

#include "modules/i2c/i2c.h"
#include "modules/mpu6050/mpu6050.h"

/* InvenSense DMP 的最高输出率和本模块采用的默认输出率。 */
#define MPU6050_DMP_MAX_RATE_HZ (200U)
#define MPU6050_DEFAULT_DMP_RATE_HZ (100U)

/* 两个 MPU6050 编译单元共享的私有实例状态。 */
struct MPU6050Instance {
    /* 指向 modules/i2c 提供的线程安全总线实例。 */
    I2CInstance *i2c;
    /* 注册时保存的配置，实例有效期内保持不变。 */
    MPU6050Config config;
    /* registered 表示总线绑定完成，initialized 表示传感器当前可读。 */
    bool registered;
    bool initialized;
    /* 成功加载 DMP 固件并打开 FIFO 后置位。 */
    bool dmp_enabled;
};

/* 校验私有实例、注册状态、I2C 句柄和保存的配置。 */
bool MPU6050InternalIsRegistered(
    const MPU6050Instance *instance);
/* 完成单字节寄存器写入。 */
bool MPU6050InternalWriteRegister(
    MPU6050Instance *instance, uint8_t register_address,
    uint8_t value);
/* 以重复起始方式从连续寄存器读取 size 字节。 */
bool MPU6050InternalReadRegisters(
    MPU6050Instance *instance, uint8_t register_address,
    uint8_t *data, size_t size);
/* 按 MPU6050 大端寄存器顺序还原二进制补码有符号值。 */
int16_t MPU6050InternalDecodeSigned16(
    uint8_t high_byte, uint8_t low_byte);
/* 对有符号整数除法执行对称的四舍五入；denominator 必须为正数。 */
int32_t MPU6050InternalDivideRoundedSigned(
    int32_t numerator, int32_t denominator);
/* 根据量程把原始加速度转换为 mg。 */
int32_t MPU6050InternalConvertAcceleration(
    int16_t raw_value, MPU6050AccelRange_e range);
/* 根据量程把原始角速度转换为毫度每秒。 */
int32_t MPU6050InternalConvertGyroscope(
    int16_t raw_value, MPU6050GyroRange_e range);

#endif
