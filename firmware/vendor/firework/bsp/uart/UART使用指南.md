# BSP UART 使用指南

## 1. 通道配置

所有 UART 当前配置为 `115200、8 数据位、无校验、1 停止位`。

| 逻辑通道 | 外设 | TX | RX | TX 方式 | RX 方式 |
| --- | --- | --- | --- | --- | --- |
| `BSP_UART_CHANNEL_DEBUG` | UART0 | PA10 | 无 | 轮询阻塞 | 无 |
| `BSP_UART_CHANNEL_1` | UART1 | PA8 | PA9 | DMA_CH1 | RX FIFO 中断，最多 16 字节批量回调 |
| `BSP_UART_CHANNEL_2` | UART2 | PB15 | PB16 | DMA_CH2 | DMA_CH4，固定 2 字节回调 |
| `BSP_UART_CHANNEL_3` | UART3 | PA26 | PA25 | DMA_CH3 | RX FIFO 中断，最多 16 字节批量回调 |

UART0 用于调试输出。UART1～UART3 用于业务通信。

## 2. 公开接口

```c
typedef void (*BSP_UART_ReceiveCallback_t)(
    const uint8_t *data, size_t size, void *context);

BSPUARTInstance *BSPUARTRegister(BSP_UART_Channel_e channel,
    BSP_UART_ReceiveCallback_t receive_callback, void *context);

bool BSPUARTSend(
    BSPUARTInstance *instance, const uint8_t *data, size_t size);
```

UART1～UART3 注册时必须提供接收回调。TX-only 的 UART0 调试通道可以传 `NULL`。

## 3. 注册接收回调

```c
static void UARTReceiveCallback(
    const uint8_t *data, size_t size, void *context)
{
    (void)context;

    /* 当前处于中断上下文，只能进行短时间、非阻塞处理。 */
    for (size_t index = 0U; index < size; ++index) {
        /* 复制数据，或使用 FreeRTOS 的 FromISR 接口通知任务。 */
    }
}

BSPUARTInstance *uart1 = BSPUARTRegister(
    BSP_UART_CHANNEL_1, UARTReceiveCallback, NULL);
```

回调中的数据指针指向 BSP 内部数据。需要在回调返回后继续使用时，必须立即复制到上层缓冲区或队列。

## 4. 不同通道的接收粒度

UART1 和 UART3 使用 RX FIFO 中断。中断服务函数会排空当前 FIFO，
每次最多把 16 个字节成批交给回调；一次中断中数据超过 16 字节时会分成
多批：

```text
收到 AA 55 → callback({AA, 55}, size=2)
收到 20 字节 → callback(前 16 字节, size=16) → callback(后 4 字节, size=4)
```

UART2 使用固定 2 字节 DMA 接收：

```text
收到 AA 55 → DMA 完成 → callback({AA, 55}, size=2) → 立即重装 DMA
```

UART2 的两个字节只是 DMA 分组，不代表完整协议帧。帧头、帧尾、长度、校验和字符串判断都应由上层协议解析器处理。
UART1/UART3 的批量大小同样不是协议边界：一条命令可能分散在多次回调中，
多条短数据也可能同批上交，上层必须按 `size` 逐字节送入自己的状态机。

## 5. 发送数据

```c
static const uint8_t message[] = "UART1 TX\r\n";

if (uart1 != NULL) {
    (void)BSPUARTSend(uart1, message, sizeof(message) - 1U);
}
```

发送行为因通道不同：

- UART0 使用轮询发送，并在有界期限内等待 UART 硬件发送完毕。
- UART1～UART3 使用 DMA 发送；函数内部有界等待 DMA 完成以及 UART FIFO、移位寄存器全部发送完毕。
- 超过 `UINT16_MAX` 的数据会分成多个 DMA 块发送。

`BSPUARTSend()` 对调用者仍是同步接口。调度器启动后，等待期间会主动让出 CPU；
若完成中断在按波特率和数据量计算出的期限内没有到达，函数会关闭 DMA、清除本次
完成标志、刷新 TX FIFO 并返回 `false`，下一次发送可重新装载通道。超时换算直接使用 SysConfig
生成的各路 `UART_*_BAUD_RATE`，修改波特率后不需维护第二份常量。

## 6. DMA 发送超时

UART1～UART3 的完成标志由 UART 中断中的 DMA TX 完成和 EOT 完成事件更新。若程序卡在等待循环，应检查：

- 全局中断是否开启
- UART NVIC 中断是否启用
- 中断服务函数名称是否与启动文件和 SysConfig 一致
- DMA 发送事件是否映射到正确通道
- 是否在关中断临界区或 ISR 中调用了阻塞发送

UART DMA 发送应在任务上下文、全局中断正常工作的情况下调用。

## 7. 接收回调限制

接收回调运行在 ISR 中，因此不要在回调中：

- 调用普通阻塞式 FreeRTOS API
- 调用 `BSPUARTSend()` 等待 DMA 完成
- 执行复杂协议解析或长循环
- 刷新 OLED 或等待 I2C

推荐在回调中只复制数据，并通过队列、任务通知或流缓冲区的 `FromISR` 接口唤醒接收任务。

## 8. 并发注意事项

BSP UART 不为发送提供 FreeRTOS 互斥锁。多个任务直接向同一个 UART 发送时，消息边界可能混合。应用层应优先使用 `modules/serial`，由模块层负责发送互斥和接收分发。

UART 协议、调试开关和业务提示信息属于 `application/communication/serial_communication` 等上层模块，不应写入 BSP。

## 9. 常见故障检查

### 收到乱码

确认双方均为 115200、8N1，并检查电平为 3.3 V TTL、TX/RX 交叉连接且共地。

### 完全不进入接收回调

确认调用了 `BSPUARTRegister()`、RX 引脚映射正确、回调非空、中断/DMA 已启用，并检查烧录的是最新构建产物。

### UART2 只发送一个字节时没有回调

UART2 当前必须累计收到 2 字节才产生 DMA 完成回调。这是固定双字节 DMA 接收的预期行为。
