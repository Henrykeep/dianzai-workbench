/**
 * @file serial.h
 * @brief 逻辑串口注册、线程安全发送和任务上下文接收接口。
 */
#ifndef SERIAL_H
#define SERIAL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** 应用层可使用的逻辑串口设备。 */
typedef enum {
    /* 115200-8-N-1 TX-only 调试串口，映射到 UART0。 */
    SERIAL_DEVICE_DEBUG = 0,
    /* 通用串口，对应硬件 UART1。 */
    SERIAL_DEVICE_UART1,
    /* 通用串口，对应硬件 UART2。 */
    SERIAL_DEVICE_UART2,
    /* 通用串口，对应硬件 UART3。 */
    SERIAL_DEVICE_UART3,
    /* 逻辑串口数量，同时作为枚举范围上限。 */
    SERIAL_DEVICE_COUNT
} Serial_Device_e;

/** 用于 SerialReceive() 的永久等待值。 */
#define SERIAL_WAIT_FOREVER_MS (UINT32_MAX)

/** 串口模块不透明实例。 */
typedef struct SerialInstance SerialInstance;

/** 注册指定逻辑串口，建立静态接收缓冲区并开启中断或 DMA 接收。 */
SerialInstance *SerialRegister(Serial_Device_e device);

/** 发送一段字节流；发送成功时返回 true。 */
bool SerialSend(
    SerialInstance *instance, const uint8_t *data, size_t size);

/**
 * @brief 从静态接收缓冲区读取数据。
 *
 * UART1/UART3 从字节流缓冲区批量读取，最多等待 timeout_ms；UART2
 * 使用固定 2 字节队列项，因此 capacity 必须至少为 2。timeout_ms 可传
 * SERIAL_WAIT_FOREVER_MS 以永久等待。
 *
 * @return 实际读取的字节数；参数非法或超时时返回 0。
 */
size_t SerialReceive(SerialInstance *instance, uint8_t *data,
    size_t capacity, uint32_t timeout_ms);

/** 返回因接收缓冲区已满而丢弃的字节总数。 */
uint32_t SerialGetDroppedReceiveCount(const SerialInstance *instance);

#endif
