# Serial Module 使用指南

`modules/serial/` 将UART中断/DMA接收、静态FreeRTOS接收缓冲区和发送互斥锁封装为统一接口。
具体协议解析属于Application层，不放在本Module中。

## 1. 串口映射

所有串口当前均为 `115200-8-N-1`。

| 逻辑设备 | TX | RX | 接收方式 | 发送方式 |
|---|---|---|---|---|
| `SERIAL_DEVICE_DEBUG` | PA10 | 无 | 不接收 | UART0轮询 |
| `SERIAL_DEVICE_UART1` | PA8 | PA9 | 单字节中断 | TX DMA |
| `SERIAL_DEVICE_UART2` | PB15 | PB16 | 每次2字节RX DMA | TX DMA |
| `SERIAL_DEVICE_UART3` | PA26 | PA25 | 单字节中断 | TX DMA |

UART0用于短调试提示。UART1～UART3的协议、帧头、字符串结束符等由Application自行
定义。

## 2. 注册串口

```c
#include "modules/serial/serial.h"

static SerialInstance *uart2;

bool ExampleSerialInit(void)
{
    uart2 = SerialRegister(SERIAL_DEVICE_UART2);
    return uart2 != NULL;
}
```

非调试串口注册时会创建128字节静态接收存储区。UART1/UART3 使用 Stream Buffer，
中断收到一批字节后可一次写入；UART2 使用固定2字节队列项，保持DMA采样边界。

## 3. 发送数据

```c
static const uint8_t message[] = "HELLO\r\n";

(void)SerialSend(uart2, message, sizeof(message) - 1U);
```

发送接口使用静态互斥锁，避免多个任务的字节流交叉。UART1～UART3虽然使用DMA，
当前接口仍会阻塞等待整段发送完成后才返回。

## 4. 接收数据

```c
uint8_t buffer[32];
size_t received_size;

received_size = SerialReceive(
    uart2, buffer, sizeof(buffer), 100U);

if (received_size > 0U) {
    /* UART2返回长度始终为2的整数倍。 */
}
```

永久等待数据：

```c
received_size = SerialReceive(
    uart2, buffer, sizeof(buffer), SERIAL_WAIT_FOREVER_MS);
```

UART1/UART3 最多等待指定时间，然后批量取出当前已有字节；UART2 只对第一个队列项
执行等待，随后继续取出已有的完整2字节项。UART2的接收缓冲区容量必须至少为2字节。

调试UART0没有接收缓冲区，对其调用 `SerialReceive()` 始终返回0。

## 5. 接收溢出诊断

```c
uint32_t dropped = SerialGetDroppedReceiveCount(uart2);
```

如果接收任务处理速度不足，ISR无法把新数据放入已满缓冲区时会增加丢弃字节计数。出现
非零值时，应提高接收任务优先级、缩短处理时间或减少协议打印。

## 6. 任务和ISR限制

- `SerialReceive()` 使用FreeRTOS Stream Buffer或队列，只能在任务上下文调用。
- `SerialSend()` 使用互斥锁和阻塞发送，不能在ISR中调用。
- 接收ISR只负责向静态接收缓冲区投递数据，不在中断中解析协议。
- UART2的2字节DMA块只是传输单位，不代表完整业务帧，协议层仍需自行组合。
- 发送较长调试信息会占用CPU或DMA等待时间，实时任务中应控制输出频率。
