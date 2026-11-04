/*
 * Serial Module 以静态队列衔接 UART ISR 和接收任务，并串行化每路发送事务。
 */
#include "modules/serial/serial.h"

#include <stddef.h>

#include "FreeRTOS.h"
#include "queue.h"
#include "semphr.h"
#include "stream_buffer.h"

#include "application/app_config.h"
#include "bsp/uart/bsp_uart.h"

#define SERIAL_RECEIVE_QUEUE_LENGTH (128U)
#define SERIAL_UART2_RECEIVE_ITEM_SIZE (2U)
#define SERIAL_RECEIVE_STREAM_CAPACITY (128U)
#define SERIAL_RECEIVE_STREAM_STORAGE_SIZE \
    (SERIAL_RECEIVE_STREAM_CAPACITY + 1U)

typedef struct {
    StaticQueue_t control;
    uint8_t storage[SERIAL_RECEIVE_QUEUE_LENGTH];
} SerialQueueReceiveResources;

typedef struct {
    StaticStreamBuffer_t control;
    uint8_t storage[SERIAL_RECEIVE_STREAM_STORAGE_SIZE];
} SerialStreamReceiveResources;

struct SerialInstance {
    /* 应用可见的逻辑串口编号。 */
    Serial_Device_e device;
    /* 真实外设句柄由 BSP 管理。 */
    BSPUARTInstance *uart;
    /* UART2 使用固定2字节队列，UART1/UART3 使用批量字节流缓冲区。 */
    QueueHandle_t receive_queue;
    StreamBufferHandle_t receive_stream;
    size_t receive_item_size;
    /* 接收缓冲区溢出计数用于运行期诊断。 */
    volatile uint32_t dropped_receive_count;
    /* 防止多个任务同时发送导致字节流交叉或 DMA 配置冲突。 */
    SemaphoreHandle_t send_mutex;
    StaticSemaphore_t send_mutex_control;
    /* 防止使用未完成注册的实例。 */
    bool registered;
};

/* 只为编译配置启用的串口保留完整队列和互斥锁，关闭项不占 SRAM。 */
#if APP_ENABLE_UART0_DEBUG != 0U
static SerialInstance serial_debug_instance;
#endif
#if APP_ENABLE_UART1 != 0U
static SerialInstance serial_uart1_instance;
static SerialStreamReceiveResources serial_uart1_receive_resources;
#endif
#if APP_ENABLE_UART2 != 0U
static SerialInstance serial_uart2_instance;
static SerialQueueReceiveResources serial_uart2_receive_resources;
#endif
#if APP_ENABLE_UART3 != 0U
static SerialInstance serial_uart3_instance;
static SerialStreamReceiveResources serial_uart3_receive_resources;
#endif

static void SerialReceiveFromISR(
    const uint8_t *data, size_t size, void *context);
static bool SerialIsValid(const SerialInstance *instance);
static SerialInstance *SerialGetConfiguredInstance(
    Serial_Device_e device);

SerialInstance *SerialRegister(Serial_Device_e device)
{
    BSP_UART_Channel_e uart_channel;
    SerialInstance *instance;

    if ((device < SERIAL_DEVICE_DEBUG) || (device >= SERIAL_DEVICE_COUNT)) {
        return NULL;
    }

    switch (device) {
        case SERIAL_DEVICE_DEBUG:
            uart_channel = BSP_UART_CHANNEL_DEBUG;
            break;
        case SERIAL_DEVICE_UART1:
            uart_channel = BSP_UART_CHANNEL_1;
            break;
        case SERIAL_DEVICE_UART2:
            uart_channel = BSP_UART_CHANNEL_2;
            break;
        case SERIAL_DEVICE_UART3:
            uart_channel = BSP_UART_CHANNEL_3;
            break;

        default:
            return NULL;
    }

    instance = SerialGetConfiguredInstance(device);
    if (instance == NULL) {
        return NULL;
    }
    if (instance->registered) {
        return instance;
    }

    instance->send_mutex =
        xSemaphoreCreateMutexStatic(&instance->send_mutex_control);
    if (instance->send_mutex == NULL) {
        return NULL;
    }

    if (device == SERIAL_DEVICE_UART2) {
#if APP_ENABLE_UART2 != 0U
        instance->receive_item_size = SERIAL_UART2_RECEIVE_ITEM_SIZE;
        instance->receive_queue = xQueueCreateStatic(
            SERIAL_RECEIVE_QUEUE_LENGTH / instance->receive_item_size,
            instance->receive_item_size,
            serial_uart2_receive_resources.storage,
            &serial_uart2_receive_resources.control);
        if (instance->receive_queue == NULL) {
            return NULL;
        }
#else
        return NULL;
#endif
    } else if (device != SERIAL_DEVICE_DEBUG) {
        SerialStreamReceiveResources *resources = NULL;

#if APP_ENABLE_UART1 != 0U
        if (device == SERIAL_DEVICE_UART1) {
            resources = &serial_uart1_receive_resources;
        }
#endif
#if APP_ENABLE_UART3 != 0U
        if (device == SERIAL_DEVICE_UART3) {
            resources = &serial_uart3_receive_resources;
        }
#endif
        if (resources == NULL) {
            return NULL;
        }
        instance->receive_item_size = sizeof(uint8_t);
        instance->receive_stream = xStreamBufferCreateStatic(
            SERIAL_RECEIVE_STREAM_STORAGE_SIZE, 1U,
            resources->storage, &resources->control);
        if (instance->receive_stream == NULL) {
            return NULL;
        }
    }

    instance->uart = BSPUARTRegister(uart_channel,
        (device == SERIAL_DEVICE_DEBUG) ? NULL : SerialReceiveFromISR,
        (device == SERIAL_DEVICE_DEBUG) ? NULL : instance);
    if (instance->uart == NULL) {
        return NULL;
    }

    instance->device                = device;
    instance->dropped_receive_count = 0U;
    instance->registered            = true;

    return instance;
}

bool SerialSend(
    SerialInstance *instance, const uint8_t *data, size_t size)
{
    bool result;

    if (!SerialIsValid(instance) || (data == NULL) || (size == 0U)) {
        return false;
    }

    if (xSemaphoreTake(instance->send_mutex, portMAX_DELAY) != pdPASS) {
        return false;
    }

    result = BSPUARTSend(instance->uart, data, size);
    (void) xSemaphoreGive(instance->send_mutex);
    return result;
}

size_t SerialReceive(SerialInstance *instance, uint8_t *data,
    size_t capacity, uint32_t timeout_ms)
{
    TickType_t wait_ticks;
    size_t received_size = 0U;

    if (!SerialIsValid(instance) ||
        ((instance->receive_queue == NULL) &&
            (instance->receive_stream == NULL)) ||
        (data == NULL) || (capacity == 0U)) {
        return 0U;
    }

    wait_ticks = (timeout_ms == SERIAL_WAIT_FOREVER_MS)
                     ? portMAX_DELAY
                     : pdMS_TO_TICKS(timeout_ms);

    if (instance->receive_stream != NULL) {
        return xStreamBufferReceive(instance->receive_stream,
            data, capacity, wait_ticks);
    }

    if ((instance->receive_queue == NULL) ||
        (capacity < instance->receive_item_size)) {
        return 0U;
    }

    /* 仅第一个队列项需要阻塞，余下完整队列项快速批量取出。 */
    if (xQueueReceive(instance->receive_queue, &data[received_size],
            wait_ticks) != pdPASS) {
        return 0U;
    }
    received_size += instance->receive_item_size;

    while (((capacity - received_size) >= instance->receive_item_size) &&
           (xQueueReceive(instance->receive_queue, &data[received_size],
                0U) == pdPASS)) {
        received_size += instance->receive_item_size;
    }

    return received_size;
}

uint32_t SerialGetDroppedReceiveCount(const SerialInstance *instance)
{
    if (!SerialIsValid(instance) ||
        ((instance->receive_queue == NULL) &&
            (instance->receive_stream == NULL))) {
        return 0U;
    }

    return instance->dropped_receive_count;
}

static void SerialReceiveFromISR(
    const uint8_t *data, size_t size, void *context)
{
    SerialInstance *instance = (SerialInstance *) context;
    BaseType_t higher_priority_task_woken = pdFALSE;
    size_t offset = 0U;

    if ((instance == NULL) ||
        ((instance->receive_queue == NULL) &&
            (instance->receive_stream == NULL)) ||
        (data == NULL) || (size == 0U) ||
        (instance->receive_item_size == 0U)) {
        return;
    }

    if (instance->receive_stream != NULL) {
        size_t sent_size = xStreamBufferSendFromISR(
            instance->receive_stream, data, size,
            &higher_priority_task_woken);

        instance->dropped_receive_count +=
            (uint32_t)(size - sent_size);
        portYIELD_FROM_ISR(higher_priority_task_woken);
        return;
    }

    /* UART2 的 DMA 帧仍按固定2字节队列项复制。 */
    while ((size - offset) >= instance->receive_item_size) {
        if (xQueueSendFromISR(instance->receive_queue, &data[offset],
                &higher_priority_task_woken) != pdPASS) {
            break;
        }
        offset += instance->receive_item_size;
    }
    instance->dropped_receive_count += (uint32_t)(size - offset);

    portYIELD_FROM_ISR(higher_priority_task_woken);
}

static bool SerialIsValid(const SerialInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->device >= SERIAL_DEVICE_DEBUG) &&
           (instance->device < SERIAL_DEVICE_COUNT) &&
           (instance->uart != NULL) && (instance->send_mutex != NULL);
}

static SerialInstance *SerialGetConfiguredInstance(
    Serial_Device_e device)
{
    switch (device) {
#if APP_ENABLE_UART0_DEBUG != 0U
        case SERIAL_DEVICE_DEBUG:
            return &serial_debug_instance;
#endif
#if APP_ENABLE_UART1 != 0U
        case SERIAL_DEVICE_UART1:
            return &serial_uart1_instance;
#endif
#if APP_ENABLE_UART2 != 0U
        case SERIAL_DEVICE_UART2:
            return &serial_uart2_instance;
#endif
#if APP_ENABLE_UART3 != 0U
        case SERIAL_DEVICE_UART3:
            return &serial_uart3_instance;
#endif
        default:
            return NULL;
    }
}
