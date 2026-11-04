/**
 * @file i2c.h
 * @brief OLED 与 MPU6050 逻辑 I2C 设备的线程安全读写接口。
 */
#ifndef I2C_H
#define I2C_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** 应用可使用的逻辑 I2C 设备总线。 */
typedef enum {
    /* 连接 SSD1306 OLED 的 I2C 总线。 */
    I2C_DEVICE_OLED = 0,
    /* 连接 MPU6050 的独立 I2C 总线。 */
    I2C_DEVICE_MPU6050,
    /* 逻辑 I2C 设备总数，同时作为枚举范围上限。 */
    I2C_DEVICE_COUNT
} I2C_Device_e;

/** I2C 模块的不透明实例。 */
typedef struct I2CInstance I2CInstance;

/** 注册指定逻辑 I2C 总线；失败时返回 NULL。 */
I2CInstance *I2CRegister(I2C_Device_e device);

/**
 * @brief 线程安全地向一个 7 位 I2C 地址写入数据。
 *
 * @return 写入成功返回 true；参数非法、超时或目标未应答时返回 false。
 */
bool I2CWrite(I2CInstance *instance, uint8_t target_address,
    const uint8_t *data, size_t size);

/** 线程安全地完成一次“写命令 + 重复起始 + 读数据”组合事务。 */
bool I2CWriteRead(I2CInstance *instance, uint8_t target_address,
    const uint8_t *write_data, size_t write_size,
    uint8_t *read_data, size_t read_size);

#endif
