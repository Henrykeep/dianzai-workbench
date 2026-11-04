/*
 * I2C BSP 提供带有限轮询、错误恢复和总线解锁的控制器写入及写后读事务。
 */
#include "bsp/i2c/bsp_i2c.h"

#include <stddef.h>

#include "FreeRTOS.h"
#include "task.h"

#include "ti_msp_dl_config.h"

#define BSP_I2C_WAIT_ITERATIONS (1000000UL)
#define BSP_I2C_START_DELAY_CYCLES (100UL)
#define BSP_I2C_YIELD_INTERVAL_MASK (0x3FFUL)
#define BSP_I2C_RECOVERY_CLOCKS (9U)
#define BSP_I2C_RECOVERY_DELAY_CYCLES (100UL)

struct BSPI2CInstance {
    /* 板级逻辑通道。 */
    BSP_I2C_Channel_e channel;
    /* 逻辑通道对应的真实 I2C 外设。 */
    I2C_Regs *regs;
    /* 防止调用方使用尚未成功注册的实例。 */
    bool registered;
};

/* I2C 资源固定，使用静态实例池避免动态内存分配。 */
static BSPI2CInstance i2c_instances[BSP_I2C_CHANNEL_COUNT];

static bool BSPI2CIsValid(const BSPI2CInstance *instance);
static bool BSPI2CWaitForIdle(I2C_Regs *regs);
static bool BSPI2CWaitForControllerTransfer(I2C_Regs *regs);
static void BSPI2CRecoverTransfer(BSPI2CInstance *instance);
static void BSPI2CRecoverBus(BSPI2CInstance *instance);
static void BSPI2CYieldWhileWaiting(uint32_t timeout);

/* 注册逻辑 I2C 通道并映射到 SysConfig 生成的真实外设。 */
BSPI2CInstance *BSPI2CRegister(BSP_I2C_Channel_e channel)
{
    BSPI2CInstance *instance;

    if ((channel < BSP_I2C_CHANNEL_OLED) ||
        (channel >= BSP_I2C_CHANNEL_COUNT)) {
        return NULL;
    }

    instance = &i2c_instances[channel];

    switch (channel) {
        case BSP_I2C_CHANNEL_OLED:
            instance->regs = I2C_OLED_INST;
            break;

        case BSP_I2C_CHANNEL_MPU6050:
            instance->regs = I2C_MPU6050_INST;
            break;

        default:
            return NULL;
    }

    instance->channel    = channel;
    instance->registered = true;
    return instance;
}

/* 轮询 TX FIFO 完成一次带超时和错误检查的 I2C 写传输。 */
bool BSPI2CWrite(BSPI2CInstance *instance, uint8_t target_address,
    const uint8_t *data, size_t size)
{
    uint32_t timeout;
    uint32_t status;
    size_t transferred_size;

    if (!BSPI2CIsValid(instance) || (target_address > 0x7FU) ||
        (data == NULL) || (size == 0U) || (size > UINT16_MAX)) {
        return false;
    }

    DL_I2C_resetControllerTransfer(instance->regs);
    DL_I2C_flushControllerTXFIFO(instance->regs);

    if (!BSPI2CWaitForIdle(instance->regs)) {
        BSPI2CRecoverTransfer(instance);
        return false;
    }

    transferred_size = DL_I2C_fillControllerTXFIFO(
        instance->regs, data, (uint16_t)size);

    DL_I2C_startControllerTransfer(instance->regs, target_address,
        DL_I2C_CONTROLLER_DIRECTION_TX, (uint16_t)size);

    /* MSPM0 I2C_ERR_13：启动传输后至少等待三个 I2C 功能时钟周期。 */
    delay_cycles(BSP_I2C_START_DELAY_CYCLES);

    timeout = BSP_I2C_WAIT_ITERATIONS;
    while (transferred_size < size) {
        status = DL_I2C_getControllerStatus(instance->regs);
        if ((status & DL_I2C_CONTROLLER_STATUS_ERROR) != 0U) {
            BSPI2CRecoverTransfer(instance);
            return false;
        }

        if (!DL_I2C_isControllerTXFIFOFull(instance->regs)) {
            DL_I2C_transmitControllerData(
                instance->regs, data[transferred_size]);
            ++transferred_size;
            timeout = BSP_I2C_WAIT_ITERATIONS;
        } else {
            if (timeout == 0U) {
                BSPI2CRecoverTransfer(instance);
                return false;
            }
            --timeout;
            BSPI2CYieldWhileWaiting(timeout);
        }
    }

    timeout = BSP_I2C_WAIT_ITERATIONS;
    while ((DL_I2C_getControllerStatus(instance->regs) &
               DL_I2C_CONTROLLER_STATUS_BUSY) != 0U) {
        if (timeout == 0U) {
            BSPI2CRecoverTransfer(instance);
            return false;
        }
        --timeout;
        BSPI2CYieldWhileWaiting(timeout);
    }

    status = DL_I2C_getControllerStatus(instance->regs);
    if ((status & DL_I2C_CONTROLLER_STATUS_ERROR) != 0U) {
        BSPI2CRecoverTransfer(instance);
        return false;
    }

    if (!BSPI2CWaitForIdle(instance->regs)) {
        BSPI2CRecoverTransfer(instance);
        return false;
    }

    return true;
}

/* 使用“写寄存器地址 + 重复 START + 读数据”完成标准寄存器读取事务。 */
bool BSPI2CWriteRead(BSPI2CInstance *instance,
    uint8_t target_address, const uint8_t *write_data,
    size_t write_size, uint8_t *read_data, size_t read_size)
{
    uint32_t timeout;
    uint32_t status;
    size_t transferred_size;
    size_t received_size = 0U;

    if (!BSPI2CIsValid(instance) || (target_address > 0x7FU) ||
        (write_data == NULL) || (write_size == 0U) ||
        (read_data == NULL) || (read_size == 0U) ||
        (write_size > UINT16_MAX) || (read_size > UINT16_MAX)) {
        return false;
    }

    DL_I2C_resetControllerTransfer(instance->regs);
    DL_I2C_flushControllerTXFIFO(instance->regs);
    DL_I2C_flushControllerRXFIFO(instance->regs);
    if (!BSPI2CWaitForIdle(instance->regs)) {
        BSPI2CRecoverTransfer(instance);
        return false;
    }

    transferred_size = DL_I2C_fillControllerTXFIFO(
        instance->regs, write_data, (uint16_t)write_size);
    DL_I2C_startControllerTransferAdvanced(instance->regs,
        target_address, DL_I2C_CONTROLLER_DIRECTION_TX,
        (uint16_t)write_size, DL_I2C_CONTROLLER_START_ENABLE,
        DL_I2C_CONTROLLER_STOP_DISABLE,
        DL_I2C_CONTROLLER_ACK_DISABLE);
    delay_cycles(BSP_I2C_START_DELAY_CYCLES);

    timeout = BSP_I2C_WAIT_ITERATIONS;
    while (transferred_size < write_size) {
        status = DL_I2C_getControllerStatus(instance->regs);
        if ((status & DL_I2C_CONTROLLER_STATUS_ERROR) != 0U) {
            BSPI2CRecoverTransfer(instance);
            return false;
        }
        if (!DL_I2C_isControllerTXFIFOFull(instance->regs)) {
            DL_I2C_transmitControllerData(
                instance->regs, write_data[transferred_size]);
            ++transferred_size;
            timeout = BSP_I2C_WAIT_ITERATIONS;
        } else {
            if (timeout == 0U) {
                BSPI2CRecoverTransfer(instance);
                return false;
            }
            --timeout;
            BSPI2CYieldWhileWaiting(timeout);
        }
    }

    /* 写阶段不发 STOP；控制器传输结束后，总线仍由本控制器保持。 */
    if (!BSPI2CWaitForControllerTransfer(instance->regs)) {
        BSPI2CRecoverTransfer(instance);
        return false;
    }

    DL_I2C_flushControllerRXFIFO(instance->regs);
    DL_I2C_startControllerTransferAdvanced(instance->regs,
        target_address, DL_I2C_CONTROLLER_DIRECTION_RX,
        (uint16_t)read_size, DL_I2C_CONTROLLER_START_ENABLE,
        DL_I2C_CONTROLLER_STOP_ENABLE,
        /* 与 TI repeated-start 官方示例一致，由控制器自动处理末字节应答。 */
        DL_I2C_CONTROLLER_ACK_DISABLE);
    delay_cycles(BSP_I2C_START_DELAY_CYCLES);

    timeout = BSP_I2C_WAIT_ITERATIONS;
    while (received_size < read_size) {
        status = DL_I2C_getControllerStatus(instance->regs);
        if ((status & DL_I2C_CONTROLLER_STATUS_ERROR) != 0U) {
            BSPI2CRecoverTransfer(instance);
            return false;
        }
        if (!DL_I2C_isControllerRXFIFOEmpty(instance->regs)) {
            read_data[received_size] =
                DL_I2C_receiveControllerData(instance->regs);
            ++received_size;
            timeout = BSP_I2C_WAIT_ITERATIONS;
        } else {
            if (timeout == 0U) {
                BSPI2CRecoverTransfer(instance);
                return false;
            }
            --timeout;
            BSPI2CYieldWhileWaiting(timeout);
        }
    }

    if (!BSPI2CWaitForControllerTransfer(instance->regs) ||
        !BSPI2CWaitForIdle(instance->regs)) {
        BSPI2CRecoverTransfer(instance);
        return false;
    }
    return true;
}

/* 检查 I2C 不透明实例是否已经成功注册。 */
static bool BSPI2CIsValid(const BSPI2CInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->channel >= BSP_I2C_CHANNEL_OLED) &&
           (instance->channel < BSP_I2C_CHANNEL_COUNT) &&
           (instance->regs != NULL);
}

/* 等待 I2C Controller 进入空闲状态，并在超时或错误时返回失败。 */
static bool BSPI2CWaitForIdle(I2C_Regs *regs)
{
    uint32_t timeout = BSP_I2C_WAIT_ITERATIONS;

    while (timeout > 0U) {
        uint32_t status = DL_I2C_getControllerStatus(regs);

        if ((status & DL_I2C_CONTROLLER_STATUS_ERROR) != 0U) {
            return false;
        }
        if ((status & DL_I2C_CONTROLLER_STATUS_IDLE) != 0U) {
            return true;
        }
        --timeout;
        BSPI2CYieldWhileWaiting(timeout);
    }

    return false;
}

/* 等待当前 burst 完成；重复起始写阶段允许 BUSBSY 保持置位。 */
static bool BSPI2CWaitForControllerTransfer(I2C_Regs *regs)
{
    uint32_t timeout = BSP_I2C_WAIT_ITERATIONS;

    while (timeout > 0U) {
        uint32_t status = DL_I2C_getControllerStatus(regs);

        if ((status & DL_I2C_CONTROLLER_STATUS_ERROR) != 0U) {
            return false;
        }
        if ((status & DL_I2C_CONTROLLER_STATUS_BUSY) == 0U) {
            return true;
        }
        --timeout;
        BSPI2CYieldWhileWaiting(timeout);
    }
    return false;
}

/* 复位失败的传输并清空 TX FIFO，为下一次访问恢复干净状态。 */
static void BSPI2CRecoverTransfer(BSPI2CInstance *instance)
{
    DL_I2C_resetControllerTransfer(instance->regs);
    DL_I2C_flushControllerTXFIFO(instance->regs);
    DL_I2C_flushControllerRXFIFO(instance->regs);
    BSPI2CRecoverBus(instance);
}

/*
 * 若从设备在字节中途复位，可能继续拉低 SDA。参考驱动的做法是临时接管
 * 对应通道的 SCL，发送最多 9 个时钟让从设备释放 SDA，再恢复该通道的
 * SysConfig I2C 复用。OLED 和 MPU6050 分别恢复各自的引脚和外设。
 */
static void BSPI2CRecoverBus(BSPI2CInstance *instance)
{
    uint32_t clock_count;

    if (!BSPI2CIsValid(instance)) {
        return;
    }

    switch (instance->channel) {
        case BSP_I2C_CHANNEL_OLED:
            DL_I2C_reset(I2C_OLED_INST);
            DL_GPIO_initDigitalOutput(GPIO_I2C_OLED_IOMUX_SCL);
            DL_GPIO_initDigitalInputFeatures(GPIO_I2C_OLED_IOMUX_SDA,
                DL_GPIO_INVERSION_DISABLE, DL_GPIO_RESISTOR_NONE,
                DL_GPIO_HYSTERESIS_DISABLE, DL_GPIO_WAKEUP_DISABLE);
            DL_GPIO_clearPins(GPIO_I2C_OLED_SCL_PORT,
                GPIO_I2C_OLED_SCL_PIN);
            DL_GPIO_enableOutput(GPIO_I2C_OLED_SCL_PORT,
                GPIO_I2C_OLED_SCL_PIN);

            for (clock_count = 0U;
                 clock_count < BSP_I2C_RECOVERY_CLOCKS; ++clock_count) {
                DL_GPIO_setPins(GPIO_I2C_OLED_SCL_PORT,
                    GPIO_I2C_OLED_SCL_PIN);
                delay_cycles(BSP_I2C_RECOVERY_DELAY_CYCLES);
                if (DL_GPIO_readPins(GPIO_I2C_OLED_SDA_PORT,
                        GPIO_I2C_OLED_SDA_PIN) != 0U) {
                    break;
                }
                DL_GPIO_clearPins(GPIO_I2C_OLED_SCL_PORT,
                    GPIO_I2C_OLED_SCL_PIN);
                delay_cycles(BSP_I2C_RECOVERY_DELAY_CYCLES);
            }

            DL_GPIO_initPeripheralInputFunctionFeatures(
                GPIO_I2C_OLED_IOMUX_SDA, GPIO_I2C_OLED_IOMUX_SDA_FUNC,
                DL_GPIO_INVERSION_DISABLE, DL_GPIO_RESISTOR_NONE,
                DL_GPIO_HYSTERESIS_DISABLE, DL_GPIO_WAKEUP_DISABLE);
            DL_GPIO_initPeripheralInputFunctionFeatures(
                GPIO_I2C_OLED_IOMUX_SCL, GPIO_I2C_OLED_IOMUX_SCL_FUNC,
                DL_GPIO_INVERSION_DISABLE, DL_GPIO_RESISTOR_NONE,
                DL_GPIO_HYSTERESIS_DISABLE, DL_GPIO_WAKEUP_DISABLE);
            DL_GPIO_enableHiZ(GPIO_I2C_OLED_IOMUX_SDA);
            DL_GPIO_enableHiZ(GPIO_I2C_OLED_IOMUX_SCL);
            DL_I2C_enablePower(I2C_OLED_INST);
            SYSCFG_DL_I2C_OLED_init();
            break;

        case BSP_I2C_CHANNEL_MPU6050:
            DL_I2C_reset(I2C_MPU6050_INST);
            DL_GPIO_initDigitalOutput(GPIO_I2C_MPU6050_IOMUX_SCL);
            DL_GPIO_initDigitalInputFeatures(GPIO_I2C_MPU6050_IOMUX_SDA,
                DL_GPIO_INVERSION_DISABLE, DL_GPIO_RESISTOR_NONE,
                DL_GPIO_HYSTERESIS_DISABLE, DL_GPIO_WAKEUP_DISABLE);
            DL_GPIO_clearPins(GPIO_I2C_MPU6050_SCL_PORT,
                GPIO_I2C_MPU6050_SCL_PIN);
            DL_GPIO_enableOutput(GPIO_I2C_MPU6050_SCL_PORT,
                GPIO_I2C_MPU6050_SCL_PIN);

            for (clock_count = 0U;
                 clock_count < BSP_I2C_RECOVERY_CLOCKS; ++clock_count) {
                DL_GPIO_setPins(GPIO_I2C_MPU6050_SCL_PORT,
                    GPIO_I2C_MPU6050_SCL_PIN);
                delay_cycles(BSP_I2C_RECOVERY_DELAY_CYCLES);
                if (DL_GPIO_readPins(GPIO_I2C_MPU6050_SDA_PORT,
                        GPIO_I2C_MPU6050_SDA_PIN) != 0U) {
                    break;
                }
                DL_GPIO_clearPins(GPIO_I2C_MPU6050_SCL_PORT,
                    GPIO_I2C_MPU6050_SCL_PIN);
                delay_cycles(BSP_I2C_RECOVERY_DELAY_CYCLES);
            }

            DL_GPIO_initPeripheralInputFunctionFeatures(
                GPIO_I2C_MPU6050_IOMUX_SDA,
                GPIO_I2C_MPU6050_IOMUX_SDA_FUNC,
                DL_GPIO_INVERSION_DISABLE, DL_GPIO_RESISTOR_NONE,
                DL_GPIO_HYSTERESIS_DISABLE, DL_GPIO_WAKEUP_DISABLE);
            DL_GPIO_initPeripheralInputFunctionFeatures(
                GPIO_I2C_MPU6050_IOMUX_SCL,
                GPIO_I2C_MPU6050_IOMUX_SCL_FUNC,
                DL_GPIO_INVERSION_DISABLE, DL_GPIO_RESISTOR_NONE,
                DL_GPIO_HYSTERESIS_DISABLE, DL_GPIO_WAKEUP_DISABLE);
            DL_GPIO_enableHiZ(GPIO_I2C_MPU6050_IOMUX_SDA);
            DL_GPIO_enableHiZ(GPIO_I2C_MPU6050_IOMUX_SCL);
            DL_I2C_enablePower(I2C_MPU6050_INST);
            SYSCFG_DL_I2C_MPU6050_init();
            break;

        default:
            break;
    }
}

/* 长轮询期间主动让出同优先级 CPU；传输仍保持同步和有界超时语义。 */
static void BSPI2CYieldWhileWaiting(uint32_t timeout)
{
    if (((timeout & BSP_I2C_YIELD_INTERVAL_MASK) == 0U) &&
        (xTaskGetSchedulerState() == taskSCHEDULER_RUNNING)) {
        taskYIELD();
    }
}
