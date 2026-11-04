/*
 * UART BSP 统一管理调试口轮询发送、UART1～UART3 DMA 发送及中断/DMA 接收分发。
 */
#include "bsp/uart/bsp_uart.h"

#include <stddef.h>

#include "FreeRTOS.h"
#include "task.h"

#include "ti_msp_dl_config.h"

#define BSP_UART2_DMA_RX_SIZE (2U)
#define BSP_UART_RX_BATCH_SIZE (16U)
#define BSP_UART_TX_BITS_PER_BYTE (10UL)
#define BSP_UART_TX_TIMEOUT_MARGIN_MS (20UL)
#define BSP_UART_RTOS_INTERRUPT_PRIORITY \
    ((uint32_t)configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY)

struct BSPUARTInstance {
    /* 板级逻辑通道，由 BSP 解析到真实 UART 外设。 */
    BSP_UART_Channel_e channel;
    /* 该逻辑通道对应的 UART 寄存器和中断号。 */
    UART_Regs *regs;
    IRQn_Type irq;
    /* 每路 UART TX 使用独立 DMA 通道，以支持并行发送。 */
    uint8_t dma_tx_channel;
    /* UART2 使用独立 RX DMA 通道，其他串口仍使用 RX 中断。 */
    uint8_t dma_rx_channel;
    uint8_t dma_rx_size;
    uint8_t dma_rx_buffer[BSP_UART2_DMA_RX_SIZE];
    /* 模块层提供的轻量级接收中断回调。 */
    BSP_UART_ReceiveCallback_t receive_callback;
    /* 传递给接收回调的所有者上下文。 */
    void *callback_context;
    /* 防止调用方使用尚未成功注册的实例。 */
    bool registered;
    /* UART TX DMA 的两个完成阶段，由对应 UART ISR 更新。 */
    volatile bool dma_tx_done;
    volatile bool uart_tx_done;
};

/* UART 资源固定，使用静态实例池避免动态内存分配。 */
static BSPUARTInstance uart_instances[BSP_UART_CHANNEL_COUNT];

static bool BSPUARTIsValid(const BSPUARTInstance *instance);
static void BSPUARTHandleInterrupt(BSPUARTInstance *instance);
static void BSPUARTArmReceiveDMA(BSPUARTInstance *instance);
static bool BSPUARTSendPolling(
    BSPUARTInstance *instance, const uint8_t *data, size_t size);
static bool BSPUARTSendDMA(
    BSPUARTInstance *instance, const uint8_t *data, size_t size);
static bool BSPUARTWaitForFlag(
    volatile const bool *flag, uint32_t timeout_ms);
static uint32_t BSPUARTCalculateTimeoutMs(
    const BSPUARTInstance *instance, size_t size);
static uint32_t BSPUARTGetBaudRate(
    const BSPUARTInstance *instance);
static void BSPUARTAbortTransmit(BSPUARTInstance *instance);
static void BSPUARTRecoverPollingTransmit(BSPUARTInstance *instance);

BSPUARTInstance *BSPUARTRegister(BSP_UART_Channel_e channel,
    BSP_UART_ReceiveCallback_t receive_callback, void *context)
{
    BSPUARTInstance *instance;

    if ((channel < BSP_UART_CHANNEL_DEBUG) ||
        (channel >= BSP_UART_CHANNEL_COUNT) ||
        ((channel != BSP_UART_CHANNEL_DEBUG) &&
            (receive_callback == NULL))) {
        return NULL;
    }

    instance = &uart_instances[channel];

    switch (channel) {
        case BSP_UART_CHANNEL_DEBUG:
            instance->regs           = UART_DEBUG_INST;
            instance->irq            = UART_DEBUG_INST_INT_IRQN;
            instance->dma_tx_channel = UINT8_MAX;
            instance->dma_rx_size    = 0U;
            break;
        case BSP_UART_CHANNEL_1:
            instance->regs           = UART_PORT1_INST;
            instance->irq            = UART_PORT1_INST_INT_IRQN;
            instance->dma_tx_channel = DMA_CH1_CHAN_ID;
            instance->dma_rx_size    = 0U;
            break;
        case BSP_UART_CHANNEL_2:
            instance->regs           = UART_PORT2_INST;
            instance->irq            = UART_PORT2_INST_INT_IRQN;
            instance->dma_tx_channel = DMA_CH2_CHAN_ID;
            instance->dma_rx_channel = DMA_CH4_CHAN_ID;
            instance->dma_rx_size    = BSP_UART2_DMA_RX_SIZE;
            break;
        case BSP_UART_CHANNEL_3:
            instance->regs           = UART_PORT3_INST;
            instance->irq            = UART_PORT3_INST_INT_IRQN;
            instance->dma_tx_channel = DMA_CH3_CHAN_ID;
            instance->dma_rx_size    = 0U;
            break;
        default:
            return NULL;
    }

    instance->channel          = channel;
    instance->receive_callback = receive_callback;
    instance->callback_context = context;
    instance->dma_tx_done      = false;
    instance->uart_tx_done     = false;
    instance->registered       = true;

    if (instance->dma_rx_size > 0U) {
        BSPUARTArmReceiveDMA(instance);
    }

    if ((channel != BSP_UART_CHANNEL_DEBUG) &&
        (receive_callback != NULL)) {
        /* 接收回调会调用 FreeRTOS FromISR API，不可使用默认优先级 0。 */
        NVIC_SetPriority(instance->irq, BSP_UART_RTOS_INTERRUPT_PRIORITY);
        NVIC_ClearPendingIRQ(instance->irq);
        NVIC_EnableIRQ(instance->irq);
    }

    return instance;
}

bool BSPUARTSend(
    BSPUARTInstance *instance, const uint8_t *data, size_t size)
{
    if (!BSPUARTIsValid(instance) || (data == NULL) || (size == 0U)) {
        return false;
    }

    /*
     * UART0 仅用于短调试提示，使用轮询发送避免调试输出
     * 依赖 DMA 完成中断而阻塞业务接收任务。UART1～UART3
     * 仍保持 DMA 发送。
     */
    return (instance->channel == BSP_UART_CHANNEL_DEBUG)
               ? BSPUARTSendPolling(instance, data, size)
               : BSPUARTSendDMA(instance, data, size);
}

void UART_DEBUG_INST_IRQHandler(void)
{
    BSPUARTHandleInterrupt(&uart_instances[BSP_UART_CHANNEL_DEBUG]);
}

void UART_PORT1_INST_IRQHandler(void)
{
    BSPUARTHandleInterrupt(&uart_instances[BSP_UART_CHANNEL_1]);
}

void UART_PORT2_INST_IRQHandler(void)
{
    BSPUARTHandleInterrupt(&uart_instances[BSP_UART_CHANNEL_2]);
}

void UART_PORT3_INST_IRQHandler(void)
{
    BSPUARTHandleInterrupt(&uart_instances[BSP_UART_CHANNEL_3]);
}

static void BSPUARTHandleInterrupt(BSPUARTInstance *instance)
{
    DL_UART_IIDX interrupt;

    if (!BSPUARTIsValid(instance)) {
        return;
    }

    interrupt = DL_UART_Main_getPendingInterrupt(instance->regs);

    switch (interrupt) {
        case DL_UART_MAIN_IIDX_DMA_DONE_TX:
            instance->dma_tx_done = true;
            break;
        case DL_UART_MAIN_IIDX_DMA_DONE_RX:
            /* UART2 每收满两个字节后整块上交，再重新装载下一次 DMA。 */
            if ((instance->receive_callback != NULL) &&
                (instance->dma_rx_size > 0U)) {
                instance->receive_callback(instance->dma_rx_buffer,
                    instance->dma_rx_size, instance->callback_context);
                BSPUARTArmReceiveDMA(instance);
            }
            break;
        case DL_UART_MAIN_IIDX_EOT_DONE:
            instance->uart_tx_done = true;
            break;
        case DL_UART_MAIN_IIDX_RX: {
            uint8_t received_data[BSP_UART_RX_BATCH_SIZE];
            size_t received_size = 0U;

            /*
             * 一次中断排空 FIFO，并成批上交给 Module。这样 UART3
             * 连续收数时每批只需一次回调和一次调度判定。
             */
            while (!DL_UART_Main_isRXFIFOEmpty(instance->regs)) {
                received_data[received_size] =
                    DL_UART_Main_receiveData(instance->regs);
                ++received_size;

                if (received_size == sizeof(received_data)) {
                    if (instance->receive_callback != NULL) {
                        instance->receive_callback(
                            received_data, received_size,
                            instance->callback_context);
                    }
                    received_size = 0U;
                }
            }
            if ((received_size > 0U) &&
                (instance->receive_callback != NULL)) {
                instance->receive_callback(received_data, received_size,
                    instance->callback_context);
            }
            break;
        }
        default:
            break;
    }
}

/* 为 UART2 配置并启动下一次固定 2 字节 RX DMA 搬运。 */
static void BSPUARTArmReceiveDMA(BSPUARTInstance *instance)
{
    DL_DMA_disableChannel(DMA, instance->dma_rx_channel);
    DL_DMA_setSrcAddr(DMA, instance->dma_rx_channel,
        (uint32_t)(uintptr_t)&instance->regs->RXDATA);
    DL_DMA_setDestAddr(DMA, instance->dma_rx_channel,
        (uint32_t)(uintptr_t)instance->dma_rx_buffer);
    DL_DMA_setTransferSize(
        DMA, instance->dma_rx_channel, instance->dma_rx_size);
    DL_DMA_enableChannel(DMA, instance->dma_rx_channel);
}

static bool BSPUARTSendPolling(
    BSPUARTInstance *instance, const uint8_t *data, size_t size)
{
    size_t index;
    uint32_t timeout_ms = BSPUARTCalculateTimeoutMs(instance, size);
    uint64_t maximum_iterations =
        ((uint64_t)CPUCLK_FREQ * timeout_ms) / 1000ULL;
    uint64_t iteration = 0ULL;

    for (index = 0U; index < size; ++index) {
        while (DL_UART_Main_isTXFIFOFull(instance->regs) &&
               (iteration < maximum_iterations)) {
            ++iteration;
        }
        if (DL_UART_Main_isTXFIFOFull(instance->regs)) {
            BSPUARTRecoverPollingTransmit(instance);
            return false;
        }
        DL_UART_Main_transmitData(instance->regs, data[index]);
    }

    /* 等待 FIFO 和移位寄存器中的最后一字节发送完成，并保持有界。 */
    while (DL_UART_Main_isBusy(instance->regs) &&
           (iteration < maximum_iterations)) {
        ++iteration;
    }
    if (DL_UART_Main_isBusy(instance->regs)) {
        BSPUARTRecoverPollingTransmit(instance);
        return false;
    }

    return true;
}

static bool BSPUARTSendDMA(
    BSPUARTInstance *instance, const uint8_t *data, size_t size)
{
    while (size > 0U) {
        uint16_t transfer_size =
            (size > UINT16_MAX) ? UINT16_MAX : (uint16_t) size;

        NVIC_DisableIRQ(instance->irq);
        DL_DMA_disableChannel(DMA, instance->dma_tx_channel);
        DL_UART_Main_clearInterruptStatus(instance->regs,
            DL_UART_MAIN_INTERRUPT_DMA_DONE_TX |
                DL_UART_MAIN_INTERRUPT_EOT_DONE);
        NVIC_ClearPendingIRQ(instance->irq);
        instance->dma_tx_done  = false;
        instance->uart_tx_done = false;

        DL_DMA_setSrcAddr(
            DMA, instance->dma_tx_channel, (uint32_t) (uintptr_t) data);
        DL_DMA_setDestAddr(DMA, instance->dma_tx_channel,
            (uint32_t) (uintptr_t) &instance->regs->TXDATA);
        DL_DMA_setTransferSize(
            DMA, instance->dma_tx_channel, transfer_size);
        DL_DMA_enableChannel(DMA, instance->dma_tx_channel);
        NVIC_EnableIRQ(instance->irq);

        /* DMA 搬运完成后，还要等待 UART FIFO 和移位寄存器发送完毕。 */
        if (!BSPUARTWaitForFlag(&instance->dma_tx_done,
                BSPUARTCalculateTimeoutMs(instance, transfer_size)) ||
            !BSPUARTWaitForFlag(&instance->uart_tx_done,
                BSPUARTCalculateTimeoutMs(instance, transfer_size))) {
            BSPUARTAbortTransmit(instance);
            return false;
        }

        data += transfer_size;
        size -= transfer_size;
    }

    return true;
}

/* 调度器启动后主动让出 CPU；启动前使用有限次数轮询避免永久阻塞。 */
static bool BSPUARTWaitForFlag(
    volatile const bool *flag, uint32_t timeout_ms)
{
    if (xTaskGetSchedulerState() == taskSCHEDULER_RUNNING) {
        TickType_t timeout_ticks = pdMS_TO_TICKS(timeout_ms);
        TickType_t start_ticks = xTaskGetTickCount();

        if (timeout_ticks == 0U) {
            timeout_ticks = 1U;
        }
        while (!*flag) {
            if ((TickType_t)(xTaskGetTickCount() - start_ticks) >=
                timeout_ticks) {
                return false;
            }
            vTaskDelay(1U);
        }
        return true;
    }

    {
        uint64_t maximum_iterations =
            ((uint64_t)CPUCLK_FREQ * timeout_ms) / 1000ULL;
        uint64_t iteration;

        for (iteration = 0ULL;
             (iteration < maximum_iterations) && !*flag; ++iteration) {
            __NOP();
        }
    }
    return *flag;
}

static uint32_t BSPUARTCalculateTimeoutMs(
    const BSPUARTInstance *instance, size_t size)
{
    uint32_t baud_rate = BSPUARTGetBaudRate(instance);
    uint64_t wire_time_ms =
        (((uint64_t)size * BSP_UART_TX_BITS_PER_BYTE * 1000ULL) +
            baud_rate - 1ULL) / baud_rate;

    wire_time_ms += BSP_UART_TX_TIMEOUT_MARGIN_MS;
    return (wire_time_ms > UINT32_MAX)
               ? UINT32_MAX
               : (uint32_t)wire_time_ms;
}

static uint32_t BSPUARTGetBaudRate(
    const BSPUARTInstance *instance)
{
    if (instance == NULL) {
        return UART_DEBUG_BAUD_RATE;
    }

    switch (instance->channel) {
        case BSP_UART_CHANNEL_1:
            return UART_PORT1_BAUD_RATE;
        case BSP_UART_CHANNEL_2:
            return UART_PORT2_BAUD_RATE;
        case BSP_UART_CHANNEL_3:
            return UART_PORT3_BAUD_RATE;
        case BSP_UART_CHANNEL_DEBUG:
        default:
            return UART_DEBUG_BAUD_RATE;
    }
}

/* 超时后只终止 TX；保留 UART2 RX DMA/FIFO，避免破坏持续接收链路。 */
static void BSPUARTAbortTransmit(BSPUARTInstance *instance)
{
    NVIC_DisableIRQ(instance->irq);
    if (instance->channel != BSP_UART_CHANNEL_DEBUG) {
        DL_DMA_disableChannel(DMA, instance->dma_tx_channel);
    }
    DL_UART_Main_clearInterruptStatus(instance->regs,
        DL_UART_MAIN_INTERRUPT_DMA_DONE_TX |
            DL_UART_MAIN_INTERRUPT_EOT_DONE);
    NVIC_ClearPendingIRQ(instance->irq);
    instance->dma_tx_done  = false;
    instance->uart_tx_done = false;
    NVIC_EnableIRQ(instance->irq);
}

/* UART0 没有接收业务，超时后可清空 FIFO，避免残留调试字节污染下次发送。 */
static void BSPUARTRecoverPollingTransmit(BSPUARTInstance *instance)
{
    BSPUARTAbortTransmit(instance);
    NVIC_DisableIRQ(instance->irq);
    DL_UART_Main_disable(instance->regs);
    DL_UART_Main_disableFIFOs(instance->regs);
    DL_UART_Main_enableFIFOs(instance->regs);
    DL_UART_Main_clearInterruptStatus(instance->regs,
        DL_UART_MAIN_INTERRUPT_DMA_DONE_TX |
            DL_UART_MAIN_INTERRUPT_EOT_DONE);
    NVIC_ClearPendingIRQ(instance->irq);
    DL_UART_Main_enable(instance->regs);
    NVIC_EnableIRQ(instance->irq);
}

static bool BSPUARTIsValid(const BSPUARTInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->channel >= BSP_UART_CHANNEL_DEBUG) &&
           (instance->channel < BSP_UART_CHANNEL_COUNT) &&
           (instance->regs != NULL);
}
