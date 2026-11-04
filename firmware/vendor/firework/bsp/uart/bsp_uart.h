/**
 * @file bsp_uart.h
 * @brief UART 逻辑通道注册、发送及接收回调板级接口。
 */
#ifndef BSP_UART_H
#define BSP_UART_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** LP-MSPM0G3507 板级层向上提供的逻辑 UART 通道。 */
typedef enum {
    /* 通过 XDS110 虚拟串口输出调试信息的 TX-only UART0。 */
    BSP_UART_CHANNEL_DEBUG = 0,
    /* UART1，映射到 PA8(TX) / PA9(RX)。 */
    BSP_UART_CHANNEL_1,
    /* UART2，映射到 PB15(TX) / PB16(RX)。 */
    BSP_UART_CHANNEL_2,
    /* UART3，映射到 PA26(TX) / PA25(RX)。 */
    BSP_UART_CHANNEL_3,
    /* 通道总数，同时作为枚举范围上限。 */
    BSP_UART_CHANNEL_COUNT
} BSP_UART_Channel_e;

/** UART 不透明实例，具体寄存器信息仅保留在 BSP 内部。 */
typedef struct BSPUARTInstance BSPUARTInstance;

/**
 * @brief UART 接收完成回调。
 *
 * @warning 该回调在中断上下文执行，只能调用 FromISR 类接口。
 */
typedef void (*BSP_UART_ReceiveCallback_t)(
    const uint8_t *data, size_t size, void *context);

/**
 * @brief 注册一个板级 UART 通道并开启接收。
 *
 * @param channel 逻辑 UART 通道。
 * @param receive_callback 接收完成时在中断中调用的回调；UART2 每次返回
 * 固定 2 字节 DMA 数据，UART1/UART3 每次返回当前 FIFO 中的一批数据，
 * TX-only 调试通道可传 NULL。
 * @param context 原样传递给接收回调的上下文指针。
 * @return 注册成功时返回非 NULL 实例，参数非法时返回 NULL。
 */
BSPUARTInstance *BSPUARTRegister(BSP_UART_Channel_e channel,
    BSP_UART_ReceiveCallback_t receive_callback, void *context);

/** 使用有界等待发送一段数据；参数非法或发送超时时返回 false。 */
bool BSPUARTSend(
    BSPUARTInstance *instance, const uint8_t *data, size_t size);

#endif
