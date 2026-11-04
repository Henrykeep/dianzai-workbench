/* I2C Module 为逻辑设备提供静态实例，并用 FreeRTOS 互斥锁保护完整总线事务。 */
#include "modules/i2c/i2c.h"

#include <stddef.h>

#include "FreeRTOS.h"
#include "semphr.h"

#include "bsp/i2c/bsp_i2c.h"

struct I2CInstance {
    /* 应用可见的逻辑 I2C 设备编号。 */
    I2C_Device_e device;
    /* 真实 I2C 外设句柄由 BSP 管理。 */
    BSPI2CInstance *i2c;
    /* 防止多个任务同时访问同一条 I2C 总线。 */
    SemaphoreHandle_t mutex;
    StaticSemaphore_t mutex_control;
    /* 防止使用未完成注册的实例。 */
    bool registered;
};

/* I2C 设备数量固定，使用静态实例池。 */
static I2CInstance i2c_instances[I2C_DEVICE_COUNT];

static bool I2CIsValid(const I2CInstance *instance);

/* 注册逻辑 I2C 设备并创建总线互斥锁。 */
I2CInstance *I2CRegister(I2C_Device_e device)
{
    BSP_I2C_Channel_e channel;
    I2CInstance *instance;

    if ((device < I2C_DEVICE_OLED) || (device >= I2C_DEVICE_COUNT)) {
        return NULL;
    }

    switch (device) {
        case I2C_DEVICE_OLED:
            channel = BSP_I2C_CHANNEL_OLED;
            break;

        case I2C_DEVICE_MPU6050:
            channel = BSP_I2C_CHANNEL_MPU6050;
            break;

        default:
            return NULL;
    }

    instance = &i2c_instances[device];
    if (instance->registered) {
        return instance;
    }

    instance->mutex = xSemaphoreCreateMutexStatic(&instance->mutex_control);
    if (instance->mutex == NULL) {
        return NULL;
    }

    instance->i2c = BSPI2CRegister(channel);
    if (instance->i2c == NULL) {
        return NULL;
    }

    instance->device     = device;
    instance->registered = true;
    return instance;
}

/* 使用互斥锁保护一次完整的 I2C 写传输。 */
bool I2CWrite(I2CInstance *instance, uint8_t target_address,
    const uint8_t *data, size_t size)
{
    bool result;

    if (!I2CIsValid(instance) || (target_address > 0x7FU) ||
        (data == NULL) || (size == 0U)) {
        return false;
    }

    if (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS) {
        return false;
    }

    result = BSPI2CWrite(instance->i2c, target_address, data, size);
    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 用同一把总线锁保护写阶段、重复起始和读阶段，防止 OLED 事务插入。 */
bool I2CWriteRead(I2CInstance *instance, uint8_t target_address,
    const uint8_t *write_data, size_t write_size,
    uint8_t *read_data, size_t read_size)
{
    bool result;

    if (!I2CIsValid(instance) || (target_address > 0x7FU) ||
        (write_data == NULL) || (write_size == 0U) ||
        (read_data == NULL) || (read_size == 0U)) {
        return false;
    }
    if (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS) {
        return false;
    }

    result = BSPI2CWriteRead(instance->i2c, target_address,
        write_data, write_size, read_data, read_size);
    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 检查 I2C 模块实例是否已经成功注册。 */
static bool I2CIsValid(const I2CInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->device >= I2C_DEVICE_OLED) &&
           (instance->device < I2C_DEVICE_COUNT) &&
           (instance->i2c != NULL) && (instance->mutex != NULL);
}
