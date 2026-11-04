/**
 * @file bsp_i2c.h
 * @brief OLED 与 MPU6050 所用 I2C 控制器的板级事务接口。
 */
#ifndef BSP_I2C_H
#define BSP_I2C_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** LP-MSPM0G3507 板级层向上提供的逻辑 I2C Controller 通道。 */
typedef enum {
    /* OLED 使用 I2C0，映射到 PA31(SCL) / PA28(SDA)。 */
    BSP_I2C_CHANNEL_OLED = 0,
    /* MPU6050 使用独立 I2C1，映射到 PB2(SCL) / PB3(SDA)。 */
    BSP_I2C_CHANNEL_MPU6050,
    /* 通道总数，同时作为枚举范围上限。 */
    BSP_I2C_CHANNEL_COUNT
} BSP_I2C_Channel_e;

/** I2C 不透明实例，真实外设寄存器仅保留在 BSP 内部。 */
typedef struct BSPI2CInstance BSPI2CInstance;

/** 注册指定板级 I2C 通道；参数非法时返回 NULL。 */
BSPI2CInstance *BSPI2CRegister(BSP_I2C_Channel_e channel);

/**
 * @brief 使用 7 位目标地址完成一次阻塞式 I2C 写传输。
 *
 * @return 传输成功返回 true；参数非法、超时或目标未应答时返回 false。
 */
bool BSPI2CWrite(BSPI2CInstance *instance, uint8_t target_address,
    const uint8_t *data, size_t size);

/**
 * @brief 先写命令/寄存器地址，再用重复起始条件读取数据。
 *
 * @return 完整写读事务成功返回 true；参数非法、超时或目标未应答时返回 false。
 */
bool BSPI2CWriteRead(BSPI2CInstance *instance,
    uint8_t target_address, const uint8_t *write_data,
    size_t write_size, uint8_t *read_data, size_t read_size);

#endif
