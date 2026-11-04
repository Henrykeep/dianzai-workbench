/* SPI Module 用静态互斥锁保护 AD9833、AD9850 和 TFT 的完整板级发送事务。 */
#include "modules/spi/spi.h"

#include <stddef.h>

#include "FreeRTOS.h"
#include "semphr.h"

#include "bsp/spi/bsp_spi.h"

struct SPIInstance {
    /* 应用可见的逻辑 SPI 设备编号。 */
    SPI_Device_e device;
    /* 真实 SPI 外设及手动片选由 BSP 管理。 */
    BSPSPIInstance *spi;
    /* 防止多个任务交错发送同一条总线上的控制字。 */
    SemaphoreHandle_t mutex;
    StaticSemaphore_t mutex_control;
    bool registered;
};

/* SPI 设备数量固定，使用静态实例池。 */
static SPIInstance spi_instances[SPI_DEVICE_COUNT];
/* DDS0 与 AD9850_0 是两个逻辑设备，但物理上共用 SPI1。 */
static SemaphoreHandle_t spi1_bus_mutex;
static StaticSemaphore_t spi1_bus_mutex_control;

static bool SPIIsValid(const SPIInstance *instance);
static SemaphoreHandle_t SPIGetBusMutex(const SPIInstance *instance);

/* 注册逻辑 SPI 设备并创建总线互斥锁。 */
SPIInstance *SPIRegister(SPI_Device_e device)
{
    BSP_SPI_Channel_e channel;
    SPIInstance *instance;

    if ((device < SPI_DEVICE_DDS_0) ||
        (device >= SPI_DEVICE_COUNT)) {
        return NULL;
    }

    switch (device) {
        case SPI_DEVICE_DDS_0:
            channel = BSP_SPI_CHANNEL_DDS_0;
            break;

        case SPI_DEVICE_AD9850_0:
            channel = BSP_SPI_CHANNEL_AD9850_0;
            break;

        case SPI_DEVICE_TFT_0:
            channel = BSP_SPI_CHANNEL_TFT_0;
            break;

        default:
            return NULL;
    }

    instance = &spi_instances[device];
    if (instance->registered) {
        return instance;
    }

    if (instance->mutex == NULL) {
        instance->mutex =
            xSemaphoreCreateMutexStatic(&instance->mutex_control);
    }

    if ((device == SPI_DEVICE_DDS_0) ||
        (device == SPI_DEVICE_AD9850_0)) {
        if (spi1_bus_mutex == NULL) {
            spi1_bus_mutex = xSemaphoreCreateMutexStatic(
                &spi1_bus_mutex_control);
        }
        if (spi1_bus_mutex == NULL) {
            return NULL;
        }
    }
    if (instance->mutex == NULL) {
        return NULL;
    }

    instance->spi = BSPSPIRegister(channel);
    if (instance->spi == NULL) {
        return NULL;
    }

    instance->device     = device;
    instance->registered = true;
    return instance;
}

/* 使用互斥锁保护一次完整的多字 SPI 写传输。 */
bool SPIWrite16(SPIInstance *instance,
    const uint16_t *words, size_t word_count)
{
    bool result;

    SemaphoreHandle_t bus_mutex;

    if (!SPIIsValid(instance) ||
        (instance->device != SPI_DEVICE_DDS_0) || (words == NULL) ||
        (word_count == 0U) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    bus_mutex = SPIGetBusMutex(instance);
    if ((bus_mutex != NULL) &&
        (xSemaphoreTake(bus_mutex, portMAX_DELAY) != pdPASS)) {
        (void)xSemaphoreGive(instance->mutex);
        return false;
    }

    result = BSPSPIWrite16(instance->spi, words, word_count);
    if (bus_mutex != NULL) {
        (void)xSemaphoreGive(bus_mutex);
    }
    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 使用互斥锁保护 TFT 的一次完整 8 位 SPI 写传输。 */
bool SPIWrite8(SPIInstance *instance,
    const uint8_t *bytes, size_t byte_count)
{
    bool result;

    if (!SPIIsValid(instance) ||
        (instance->device != SPI_DEVICE_TFT_0) ||
        (bytes == NULL) || (byte_count == 0U) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = BSPSPIWrite8(instance->spi, bytes, byte_count);
    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* AD9850 的格式切换、5 字节传输和 FQ_UD 脉冲全部在 SPI1 共用锁内完成。 */
bool SPIWriteAD9850Frame(SPIInstance *instance,
    const uint8_t *bytes, size_t byte_count)
{
    bool result;
    SemaphoreHandle_t bus_mutex;

    if (!SPIIsValid(instance) ||
        (instance->device != SPI_DEVICE_AD9850_0) ||
        (bytes == NULL) || (byte_count == 0U) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    bus_mutex = SPIGetBusMutex(instance);
    if ((bus_mutex == NULL) ||
        (xSemaphoreTake(bus_mutex, portMAX_DELAY) != pdPASS)) {
        (void)xSemaphoreGive(instance->mutex);
        return false;
    }

    result = BSPSPIWriteAD9850Frame(instance->spi, bytes, byte_count);
    (void)xSemaphoreGive(bus_mutex);
    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 检查 SPI 模块实例是否已经成功注册。 */
static bool SPIIsValid(const SPIInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->device >= SPI_DEVICE_DDS_0) &&
           (instance->device < SPI_DEVICE_COUNT) &&
           (instance->spi != NULL) && (instance->mutex != NULL);
}

/* TFT 不需要跨设备仲裁；两个 DDS 逻辑设备则固定共用 SPI1 锁。 */
static SemaphoreHandle_t SPIGetBusMutex(const SPIInstance *instance)
{
    if ((instance != NULL) &&
        ((instance->device == SPI_DEVICE_DDS_0) ||
         (instance->device == SPI_DEVICE_AD9850_0))) {
        return spi1_bus_mutex;
    }
    return NULL;
}
