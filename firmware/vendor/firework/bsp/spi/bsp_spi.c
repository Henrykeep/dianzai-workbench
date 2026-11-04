/*
 * SPI BSP 为 AD9833、AD9850 和 TFT 提供各自的数据宽度、时序及手动片选事务。
 */
#include "bsp/spi/bsp_spi.h"

#include <stddef.h>

#include "ti_msp_dl_config.h"

#define BSP_SPI_WAIT_ITERATIONS (1000000UL)

struct BSPSPIInstance {
    /* 板级逻辑通道及其对应的真实 SPI 外设。 */
    BSP_SPI_Channel_e channel;
    SPI_Regs *regs;
    /* 两个设备都使用独立 GPIO 手动控制片选。 */
    GPIO_Regs *select_port;
    uint32_t select_pin;
    bool registered;
};

/* SPI 资源固定，使用静态实例池避免动态内存分配。 */
static BSPSPIInstance spi_instances[BSP_SPI_CHANNEL_COUNT];

static bool BSPSPIIsValid(const BSPSPIInstance *instance);
static bool BSPSPIWaitUntilIdle(const BSPSPIInstance *instance);
static void BSPSPIDrainReceiveFIFO(
    const BSPSPIInstance *instance, bool data_size_16);
static void BSPSPIConfigureAD9833Format(SPI_Regs *regs);
static void BSPSPIConfigureAD9850Format(SPI_Regs *regs);

/* 注册指定 SPI 通道，并保证对应设备的手动片选初始处于无效高电平。 */
BSPSPIInstance *BSPSPIRegister(BSP_SPI_Channel_e channel)
{
    BSPSPIInstance *instance;

    if ((channel < BSP_SPI_CHANNEL_DDS_0) ||
        (channel >= BSP_SPI_CHANNEL_COUNT)) {
        return NULL;
    }

    instance = &spi_instances[channel];
    if (instance->registered) {
        return instance;
    }

    switch (channel) {
        case BSP_SPI_CHANNEL_DDS_0:
            instance->regs = SPI_DDS_INST;
            instance->select_port = GPIO_DDS_PORT;
            instance->select_pin =
                GPIO_DDS_AD9833_FSYNC_PIN;
            break;

        case BSP_SPI_CHANNEL_AD9850_0:
            instance->regs = SPI_DDS_INST;
            instance->select_port = NULL;
            instance->select_pin = 0U;
            break;

        case BSP_SPI_CHANNEL_TFT_0:
            instance->regs        = SPI_TFT_INST;
            instance->select_port = GPIO_TFT_PORT;
            instance->select_pin  = GPIO_TFT_TFT_CS_PIN;
            break;

        default:
            return NULL;
    }

    instance->channel    = channel;
    instance->registered = true;
    if (!DL_SPI_isPowerEnabled(instance->regs)) {
        instance->registered = false;
        return NULL;
    }
    /* BSP 安全启动会关闭 SPI；设备首次注册时再按需恢复对应总线。 */
    if (!DL_SPI_isEnabled(instance->regs)) {
        DL_SPI_enable(instance->regs);
    }
    if (instance->channel == BSP_SPI_CHANNEL_DDS_0) {
        DL_GPIO_setPins(instance->select_port, instance->select_pin);
    }
    /* 不论先注册哪一个后端，都先让 AD9833 失能。 */
    if ((instance->channel == BSP_SPI_CHANNEL_DDS_0) ||
        (instance->channel == BSP_SPI_CHANNEL_AD9850_0)) {
        DL_GPIO_setPins(GPIO_DDS_PORT, GPIO_DDS_AD9833_FSYNC_PIN);
        DL_GPIO_clearPins(GPIO_DDS_PORT, GPIO_DDS_AD9850_FQ_UD_PIN);
        BSPSPIConfigureAD9833Format(instance->regs);
    }
    BSPSPIDrainReceiveFIFO(
        instance, channel == BSP_SPI_CHANNEL_DDS_0);
    return instance;
}

/* 手动控制 FSYNC，并带超时地完成一组连续 16 位 SPI 写入。 */
bool BSPSPIWrite16(BSPSPIInstance *instance,
    const uint16_t *words, size_t word_count)
{
    size_t index;

    if (!BSPSPIIsValid(instance) ||
        (instance->channel != BSP_SPI_CHANNEL_DDS_0) || (words == NULL) ||
        (word_count == 0U) || !BSPSPIWaitUntilIdle(instance)) {
        return false;
    }

    BSPSPIDrainReceiveFIFO(instance, true);
    DL_GPIO_clearPins(
        instance->select_port, instance->select_pin);

    for (index = 0U; index < word_count; ++index) {
        uint32_t timeout = BSP_SPI_WAIT_ITERATIONS;

        while (DL_SPI_isTXFIFOFull(instance->regs)) {
            if (timeout == 0U) {
                DL_GPIO_setPins(instance->select_port,
                    instance->select_pin);
                return false;
            }
            --timeout;
        }

        DL_SPI_transmitData16(instance->regs, words[index]);
        if (!BSPSPIWaitUntilIdle(instance)) {
            DL_GPIO_setPins(instance->select_port,
                instance->select_pin);
            return false;
        }
        BSPSPIDrainReceiveFIFO(instance, true);
    }

    DL_GPIO_setPins(
        instance->select_port, instance->select_pin);
    return true;
}

/* 手动控制 TFT CS，连续发送命令参数或像素数据。 */
bool BSPSPIWrite8(BSPSPIInstance *instance,
    const uint8_t *bytes, size_t byte_count)
{
    size_t index;

    if (!BSPSPIIsValid(instance) ||
        (instance->channel != BSP_SPI_CHANNEL_TFT_0) ||
        (bytes == NULL) || (byte_count == 0U) ||
        !BSPSPIWaitUntilIdle(instance)) {
        return false;
    }

    BSPSPIDrainReceiveFIFO(instance, false);
    DL_GPIO_clearPins(instance->select_port, instance->select_pin);

    for (index = 0U; index < byte_count; ++index) {
        uint32_t timeout = BSP_SPI_WAIT_ITERATIONS;

        while (DL_SPI_isTXFIFOFull(instance->regs)) {
            BSPSPIDrainReceiveFIFO(instance, false);
            if (timeout == 0U) {
                DL_GPIO_setPins(
                    instance->select_port, instance->select_pin);
                return false;
            }
            --timeout;
        }
        DL_SPI_transmitData8(instance->regs, bytes[index]);
        BSPSPIDrainReceiveFIFO(instance, false);
    }

    if (!BSPSPIWaitUntilIdle(instance)) {
        DL_GPIO_setPins(instance->select_port, instance->select_pin);
        return false;
    }
    BSPSPIDrainReceiveFIFO(instance, false);
    DL_GPIO_setPins(instance->select_port, instance->select_pin);
    return true;
}

/* AD9850 使用 5 字节、LSB first 串行帧；锁存和恢复格式必须是同一原子操作。 */
bool BSPSPIWriteAD9850Frame(BSPSPIInstance *instance,
    const uint8_t *bytes, size_t byte_count)
{
    size_t index;
    bool result = false;

    if (!BSPSPIIsValid(instance) ||
        (instance->channel != BSP_SPI_CHANNEL_AD9850_0) ||
        (bytes == NULL) || (byte_count == 0U) ||
        !BSPSPIWaitUntilIdle(instance)) {
        return false;
    }

    /* AD9833 不支持片选悬空时的时钟，传 AD9850 前始终拉高 FSYNC。 */
    DL_GPIO_setPins(GPIO_DDS_PORT, GPIO_DDS_AD9833_FSYNC_PIN);
    DL_GPIO_clearPins(GPIO_DDS_PORT, GPIO_DDS_AD9850_FQ_UD_PIN);
    DL_SPI_disable(instance->regs);
    BSPSPIConfigureAD9850Format(instance->regs);
    DL_SPI_enable(instance->regs);
    BSPSPIDrainReceiveFIFO(instance, false);

    for (index = 0U; index < byte_count; ++index) {
        uint32_t timeout = BSP_SPI_WAIT_ITERATIONS;

        while (DL_SPI_isTXFIFOFull(instance->regs)) {
            if (timeout == 0U) {
                goto restore_format;
            }
            --timeout;
        }
        DL_SPI_transmitData8(instance->regs, bytes[index]);
        if (!BSPSPIWaitUntilIdle(instance)) {
            goto restore_format;
        }
        BSPSPIDrainReceiveFIFO(instance, false);
    }

    /* FQ_UD 上升沿把 40 位调谐字一次性送入输出寄存器。 */
    DL_GPIO_setPins(GPIO_DDS_PORT, GPIO_DDS_AD9850_FQ_UD_PIN);
    DL_GPIO_clearPins(GPIO_DDS_PORT, GPIO_DDS_AD9850_FQ_UD_PIN);
    result = true;

restore_format:
    DL_SPI_disable(instance->regs);
    BSPSPIConfigureAD9833Format(instance->regs);
    DL_SPI_enable(instance->regs);
    BSPSPIDrainReceiveFIFO(instance, true);
    return result;
}

/* 检查 SPI 实例、寄存器和手动片选映射是否有效。 */
static bool BSPSPIIsValid(const BSPSPIInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->channel >= BSP_SPI_CHANNEL_DDS_0) &&
           (instance->channel < BSP_SPI_CHANNEL_COUNT) &&
           (instance->regs != NULL) &&
           (((instance->channel == BSP_SPI_CHANNEL_AD9850_0)) ||
            ((instance->select_port != NULL) &&
             (instance->select_pin != 0U)));
}

/* SysConfig 默认格式，也是 AD9833 所需的 SPI Mode 2、16 位、MSB first。 */
static void BSPSPIConfigureAD9833Format(SPI_Regs *regs)
{
    DL_SPI_setFrameFormat(regs, DL_SPI_FRAME_FORMAT_MOTO3_POL1_PHA0);
    DL_SPI_setDataSize(regs, DL_SPI_DATA_SIZE_16);
    DL_SPI_setBitOrder(regs, DL_SPI_BIT_ORDER_MSB_FIRST);
}

/* AD9850 串行口在 SCLK 上升沿采样，数据与最低位先到达。 */
static void BSPSPIConfigureAD9850Format(SPI_Regs *regs)
{
    DL_SPI_setFrameFormat(regs, DL_SPI_FRAME_FORMAT_MOTO3_POL0_PHA0);
    DL_SPI_setDataSize(regs, DL_SPI_DATA_SIZE_8);
    DL_SPI_setBitOrder(regs, DL_SPI_BIT_ORDER_LSB_FIRST);
}

/* 等待移位器和 FIFO 完成当前传输，避免释放片选时仍有时钟。 */
static bool BSPSPIWaitUntilIdle(const BSPSPIInstance *instance)
{
    uint32_t timeout = BSP_SPI_WAIT_ITERATIONS;

    while (DL_SPI_isBusy(instance->regs)) {
        if (timeout == 0U) {
            return false;
        }
        --timeout;
    }

    return true;
}

/* 当前两个设备都只写，清除 SPI 同步产生但无人使用的接收数据。 */
static void BSPSPIDrainReceiveFIFO(
    const BSPSPIInstance *instance, bool data_size_16)
{
    while (!DL_SPI_isRXFIFOEmpty(instance->regs)) {
        if (data_size_16) {
            (void)DL_SPI_receiveData16(instance->regs);
        } else {
            (void)DL_SPI_receiveData8(instance->regs);
        }
    }
}
