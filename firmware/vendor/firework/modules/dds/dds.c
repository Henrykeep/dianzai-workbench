/*
 * DDS Module 统一 AD9833 与 AD9850 后端，保存线程安全的频率、相位、波形和启停状态。
 */
#include "modules/dds/dds.h"

#include "application/app_config.h"

#if (APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U) || \
    (APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U)

#include <stddef.h>

#include "FreeRTOS.h"
#include "semphr.h"

#include "modules/dds/ad9833.h"
#include "modules/dds/ad9850.h"
#include "modules/spi/spi.h"

typedef union {
    AD9833Context ad9833;
    AD9850Context ad9850;
} DDSDriverContext;

struct DDSInstance {
    /* 通用逻辑设备、芯片类型及其底层 SPI 总线。 */
    DDS_Device_e device;
    DDSChip_e chip;
    SPIInstance *spi;
    DDSDriverContext driver_context;
    /* 最近一次成功写入的逻辑状态。 */
    DDSState state;
    /* 固定锁顺序为 DDS mutex -> SPI mutex。 */
    SemaphoreHandle_t mutex;
    StaticSemaphore_t mutex_control;
    bool registered;
};

/* DDS 设备数量固定，使用静态实例池。 */
static DDSInstance dds_instances[DDS_DEVICE_COUNT];

static bool DDSIsValid(const DDSInstance *instance);
static bool DDSDriverInitialize(
    DDSInstance *instance, const DDSConfig *config);
static bool DDSDriverSetFrequency(
    DDSInstance *instance, uint32_t frequency_hz);
static bool DDSDriverSetPhase(
    DDSInstance *instance, uint16_t phase_degrees);
static bool DDSDriverSetWaveform(
    DDSInstance *instance, DDSWaveform_e waveform);
static bool DDSDriverSetEnabled(DDSInstance *instance, bool enabled);

/* 注册逻辑 DDS，选择芯片后端并一次写入完整初始配置。 */
DDSInstance *DDSRegister(DDS_Device_e device, const DDSConfig *config)
{
    SPI_Device_e spi_device;
    DDSInstance *instance;

    if ((device < DDS_DEVICE_OUTPUT_0) ||
        (device >= DDS_DEVICE_COUNT) || (config == NULL) ||
        (config->chip < DDS_CHIP_AD9833) ||
        (config->chip >= DDS_CHIP_COUNT) ||
        (config->initial_waveform < DDS_WAVEFORM_SINE) ||
        (config->initial_waveform >= DDS_WAVEFORM_COUNT)) {
        return NULL;
    }

    switch (device) {
        case DDS_DEVICE_OUTPUT_0:
            spi_device = SPI_DEVICE_DDS_0;
            break;

        case DDS_DEVICE_OUTPUT_1:
            spi_device = SPI_DEVICE_AD9850_0;
            break;

        default:
            return NULL;
    }

    instance = &dds_instances[device];
    if (instance->registered) {
        return instance;
    }

    if (instance->mutex == NULL) {
        instance->mutex =
            xSemaphoreCreateMutexStatic(&instance->mutex_control);
    }
    if (instance->mutex == NULL) {
        return NULL;
    }

    instance->spi = SPIRegister(spi_device);
    if (instance->spi == NULL) {
        return NULL;
    }

    instance->device = device;
    instance->chip   = config->chip;
    if (!DDSDriverInitialize(instance, config)) {
        return NULL;
    }

    instance->state.chip               = config->chip;
    instance->state.reference_clock_hz = config->reference_clock_hz;
    instance->state.frequency_hz        = config->initial_frequency_hz;
    instance->state.phase_degrees       = config->initial_phase_degrees;
    instance->state.waveform            = config->initial_waveform;
    instance->state.enabled             = config->start_enabled;
    instance->registered                = true;
    return instance;
}

/* 线程安全地更新频率，并仅在硬件发送成功后修改状态。 */
bool DDSSetFrequency(DDSInstance *instance, uint32_t frequency_hz)
{
    bool result;

    if (!DDSIsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = DDSDriverSetFrequency(instance, frequency_hz);
    if (result) {
        instance->state.frequency_hz = frequency_hz;
    }

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 线程安全地更新相位，并仅在硬件发送成功后修改状态。 */
bool DDSSetPhase(DDSInstance *instance, uint16_t phase_degrees)
{
    bool result;

    if (!DDSIsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = DDSDriverSetPhase(instance, phase_degrees);
    if (result) {
        instance->state.phase_degrees = phase_degrees;
    }

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 线程安全地切换波形，并保持当前频率、相位和启停状态。 */
bool DDSSetWaveform(DDSInstance *instance, DDSWaveform_e waveform)
{
    bool result;

    if (!DDSIsValid(instance) ||
        (waveform < DDS_WAVEFORM_SINE) ||
        (waveform >= DDS_WAVEFORM_COUNT) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = DDSDriverSetWaveform(instance, waveform);
    if (result) {
        instance->state.waveform = waveform;
    }

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 线程安全地清除复位和休眠位，恢复当前波形。 */
bool DDSStart(DDSInstance *instance)
{
    bool result;

    if (!DDSIsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = DDSDriverSetEnabled(instance, true);
    if (result) {
        instance->state.enabled = true;
    }

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 线程安全地置位复位和休眠位，停止波形发生。 */
bool DDSStop(DDSInstance *instance)
{
    bool result;

    if (!DDSIsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = DDSDriverSetEnabled(instance, false);
    if (result) {
        instance->state.enabled = false;
    }

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

/* 在 DDS 锁内一次复制完整状态，避免调用方读取到混合快照。 */
bool DDSGetState(DDSInstance *instance, DDSState *state)
{
    if (!DDSIsValid(instance) || (state == NULL) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    *state = instance->state;
    (void)xSemaphoreGive(instance->mutex);
    return true;
}

/* 检查通用 DDS 实例及其底层资源是否有效。 */
static bool DDSIsValid(const DDSInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->device >= DDS_DEVICE_OUTPUT_0) &&
           (instance->device < DDS_DEVICE_COUNT) &&
           (instance->chip >= DDS_CHIP_AD9833) &&
           (instance->chip < DDS_CHIP_COUNT) &&
           (instance->spi != NULL) && (instance->mutex != NULL);
}

/* 根据芯片类型调用对应的初始化后端。 */
static bool DDSDriverInitialize(
    DDSInstance *instance, const DDSConfig *config)
{
    switch (instance->chip) {
        case DDS_CHIP_AD9833:
            return AD9833Initialize(&instance->driver_context.ad9833,
                instance->spi, config->reference_clock_hz,
                config->initial_frequency_hz,
                config->initial_phase_degrees,
                config->initial_waveform, config->start_enabled);

        case DDS_CHIP_AD9850:
            if ((config->initial_phase_degrees != 0U) ||
                (config->initial_waveform == DDS_WAVEFORM_TRIANGLE)) {
                return false;
            }
            return AD9850Initialize(&instance->driver_context.ad9850,
                instance->spi, config->reference_clock_hz,
                config->initial_frequency_hz,
                config->initial_waveform, config->start_enabled);

        default:
            return false;
    }
}

/* 根据芯片类型调用对应的频率写入后端。 */
static bool DDSDriverSetFrequency(
    DDSInstance *instance, uint32_t frequency_hz)
{
    switch (instance->chip) {
        case DDS_CHIP_AD9833:
            return AD9833SetFrequency(&instance->driver_context.ad9833,
                instance->spi, instance->state.reference_clock_hz,
                frequency_hz);

        case DDS_CHIP_AD9850:
            return AD9850SetFrequency(&instance->driver_context.ad9850,
                instance->spi, instance->state.reference_clock_hz,
                frequency_hz);

        default:
            return false;
    }
}

/* 根据芯片类型调用对应的相位写入后端。 */
static bool DDSDriverSetPhase(
    DDSInstance *instance, uint16_t phase_degrees)
{
    switch (instance->chip) {
        case DDS_CHIP_AD9833:
            return AD9833SetPhase(&instance->driver_context.ad9833,
                instance->spi, phase_degrees);

        case DDS_CHIP_AD9850:
            /* AD9850 串行协议没有相位寄存器。 */
            (void)phase_degrees;
            return false;

        default:
            return false;
    }
}

/* 根据芯片类型调用对应的波形控制后端。 */
static bool DDSDriverSetWaveform(
    DDSInstance *instance, DDSWaveform_e waveform)
{
    switch (instance->chip) {
        case DDS_CHIP_AD9833:
            return AD9833SetWaveform(&instance->driver_context.ad9833,
                instance->spi, waveform);

        case DDS_CHIP_AD9850:
            return AD9850SetWaveform(&instance->driver_context.ad9850,
                instance->spi, waveform);

        default:
            return false;
    }
}

/* 根据芯片类型调用对应的启停控制后端。 */
static bool DDSDriverSetEnabled(DDSInstance *instance, bool enabled)
{
    switch (instance->chip) {
        case DDS_CHIP_AD9833:
            return AD9833SetEnabled(&instance->driver_context.ad9833,
                instance->spi, enabled);

        case DDS_CHIP_AD9850:
            return AD9850SetEnabled(&instance->driver_context.ad9850,
                instance->spi, enabled);

        default:
            return false;
    }
}

#endif /* AD9833/AD9850 output */
