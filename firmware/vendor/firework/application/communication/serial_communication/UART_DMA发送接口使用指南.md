# 串口通信与 DMA 接口使用指南

本目录是 Application 层的串口业务入口：注册 UART0～UART3，创建接收任务，
封装线程安全发送，解析 UART1/UART2/UART3 协议，并可把 ADC 窗口以 VOFA+
JustFloat 从 UART2 发出。底层队列、DMA、中断和引脚封装分别在
`modules/serial` 与 `bsp/uart`。

## 当前开关和引脚

| 串口 | 引脚 | 当前默认 | 用途 |
| --- | --- | ---: | --- |
| UART0 | PA10 TX | 开 | 115200-8-N-1 轮询调试输出 |
| UART1 | PA8 TX / PA9 RX | 关 | 32 字节负载的示例二进制帧协议 |
| UART2 | PB15 TX / PB16 RX | 关 | 双字节 DMA 收样本；可发送 JustFloat |
| UART3 | PA26 TX / PA25 RX | 开 | 上位机数据/文本协议与可选通用样本流 |

所有串口均为 115200-8-N-1。配置位于 `application/app_config.h`：

```c
#define APP_ENABLE_UART0_DEBUG (1U)
#define APP_ENABLE_UART1       (0U)
#define APP_ENABLE_UART2       (0U)
#define APP_ENABLE_UART3       (1U)
```

关闭 UART1～UART3 后不会注册对应逻辑串口，也不会分配接收任务的静态 TCB 和栈。
UART0 总开关关闭时，Application 的调试发送会静默返回成功，业务串口不受影响。

## 初始化和通用发送

顶层 `ApplicationInit()` 已调用：

```c
bool SerialCommunicationInit(void);
```

它先初始化 UART0，再按开关初始化 UART1～UART3。也可单独调用
`SerialCommunicationUARTxInit()`；重复初始化会复用已有实例和任务。

发送接口：

```c
bool SerialCommunicationUART0Send(const uint8_t *data, size_t size);
bool SerialCommunicationUART1Send(const uint8_t *data, size_t size);
bool SerialCommunicationUART2Send(const uint8_t *data, size_t size);
bool SerialCommunicationUART3Send(const uint8_t *data, size_t size);
```

UART1～UART3 使用底层 DMA 发送并由静态互斥锁串行化，UART0 使用轮询。接口只接收
非空指针和非零长度；不自动追加 NUL、CRLF 或协议帧尾。调用方必须明确传入真实长度：

```c
static const uint8_t command[] = "sep1\r\n";
(void)SerialCommunicationUART3Send(command, sizeof(command) - 1U);
```

底层发送超时按 115200 baud 的线上时间加 20 ms 余量计算。发送失败会累加：

```c
uint32_t failures = SerialCommunicationGetTransmitFailureCount(3U);
```

接收缓冲区满时的累计丢字节数：

```c
uint32_t dropped = SerialCommunicationGetDroppedReceiveCount(3U);
```

参数 `uart_number` 为 1～3；发送失败查询也允许 0 表示 UART0。

## UART1 示例帧协议

UART1 帧格式：

```text
AA 55 LEN CMD PAYLOAD... CHECKSUM
```

- `LEN` 为 0～32 字节负载长度；
- `CHECKSUM` 是 `LEN + CMD + 所有 PAYLOAD` 的 8 位和；
- 状态机跨接收批次保留半包，可处理粘包和拆包；
- 长度超限、校验错误或无效状态会复位到等待帧头。

当前示例命令：

| 请求 CMD | 请求负载 | 响应 |
| ---: | --- | --- |
| `0x01` | 任意，通常空 | `0x81` + `PONG` |
| `0x02` | 0～32 字节 | `0x82` + 原样负载 |
| 其他 | 任意合法负载 | `0xFF` + 原始命令字节 |

这套 32 字节限制只属于 UART1 示例协议，不是 UART3 文本行长度。

## UART2 输入样本

UART2 RX 使用 DMA 每次接收 2 字节，但业务帧仍为 4 字节：

```text
AA  DATA_H  DATA_L  55
```

`DATA_H/DATA_L` 是有符号 `int16_t` 大端值。解析成功后，在 UART2 接收任务上下文
向最多 4 个订阅者发布：

```c
bool SerialCommunicationUART2SubscribeSample(
    SerialCommunicationUART2SampleCallback_t callback, void *context);

bool SerialCommunicationUART2UnsubscribeSample(
    SerialCommunicationUART2SampleCallback_t callback, void *context);
```

相同 `callback/context` 重复订阅视为成功。回调应只做快速复制、置位或队列投递，
不能阻塞。取消时接收任务可能已经取得回调快照，因此返回后最多还会再回调一次；
`context` 必须保持有效到本轮分发结束。

显示菜单的路径是 `WAVEFORM → UART2 PB16`，收满 1024 个合法样本后显示最后
128 点；FFT UART2 每 64 点形成一帧。

## UART2 ADC JustFloat 输出

该功能默认关闭，依赖 UART2、Waveform Measurement 和所选 ADC 输入：

```c
#define APP_ENABLE_UART2         (1U)
#define APP_ENABLE_ADC_JUSTFLOAT (1U)
#define APP_ADC_JUSTFLOAT_DEFAULT_SOURCE (0U) /* 0=PA27，1=PB19 */
```

每次完整 ADC 测量发布后，任务复制最后 128 个原始 12 位码。每个值转换为小端
32 位 `float`，后接 VOFA+ JustFloat 固定尾 `00 00 80 7F`，共 8 字节/样本。
因此一次标准窗口发送 1024 字节。

运行期接口：

```c
bool ADCJustFloatInit(void);
bool ADCJustFloatIsReady(void);
bool ADCSamplingUART2SetSource(ADCSamplingUART2Source_e source);
ADCSamplingUART2Source_e ADCSamplingUART2GetSource(void);
bool ADCSamplingUART2SetCustomSource(
    ADCSamplingUART2CustomSourceRead_t read, void *context);
```

枚举 `ADC_SAMPLING_UART2_SOURCE_PA21` 是旧版兼容名，当前实际 ADC 是 PB19/ADC1.6。
自定义源回调每次最多填 128 个 `float`；它在发送任务中执行，不应长时间阻塞。

## UART3 三类输入

UART3 接收路由顺序固定为：正在进行的数据事务 → 已注册文本行观察者 → 兼容
ASCII 样本 → `HELLO/PING` 调试解析。这样数据响应不会被误当作普通波形。

### 可选二进制样本

`APP_ENABLE_UART3_BINARY_WAVEFORM=1U` 时解析：

```text
AA  DATA_H  DATA_L  55
```

### 可选 ASCII 电压样本

`APP_ENABLE_UART3_ASCII_WAVEFORM=1U` 时，空闲状态下可接收诸如：

```text
0.57385\r\n
-0.12000\r\n
```

解析器最多保留 5 位小数并换算为有符号毫伏；超出 `int16_t` 毫伏范围或包含多余
字符时拒绝。CR、LF、CRLF 和 NUL 都能结束接收行，但固件主动发送的新协议命令
统一使用 CRLF。

这两类样本都通过最多 4 个 UART3 样本订阅者发布：

```c
bool SerialCommunicationUART3SubscribeSample(
    SerialCommunicationUART3SampleCallback_t callback, void *context);
bool SerialCommunicationUART3UnsubscribeSample(
    SerialCommunicationUART3SampleCallback_t callback, void *context);
```

### 文本行观察者

```c
bool SerialCommunicationUART3SubscribeLine(
    SerialCommunicationUART3LineCallback_t callback, void *context);
bool SerialCommunicationUART3UnsubscribeLine(
    SerialCommunicationUART3LineCallback_t callback, void *context);
```

最多 2 个观察者。任一回调返回 `true` 表示已消费该行，不再进入兼容 ASCII 或
`HELLO/PING` 处理。UART3 行缓冲区为 512 字节，实际可完整保存最多 512 个非结束符
字节；再来的字节会把本行标为溢出并一直丢弃到 CR/LF/NUL。普通空闲状态会在 UART0
提示 `UART3 STRING TOO LONG`，数据准备期间静默丢弃长进度日志。

## UART3 的 21 条数据命令

所有固件请求都以 `\r\n` 结束。建议菜单和“重新测量”调用：

```c
bool SerialCommunicationUART3RequestPreparedData(
    SerialCommunicationUART3DataType_e type);
```

它会先按类型发送 `sep1`、`sep2` 或 `sweep1`，看到 READY/DONE 后自动发最终命令。
已经由其他流程完成准备时才使用直接接口：

```c
bool SerialCommunicationUART3RequestData(
    SerialCommunicationUART3DataType_e type);
```

上一事务仍在准备或收数时，新请求返回 `false`。退出页面或切换来源应调用：

```c
void SerialCommunicationUART3CancelRequest(void);
```

### 10 条帧式 128 点命令

| 最终命令 | 内容 | 准备命令 |
| --- | --- | --- |
| `lwavea1` / `lwavea3` | A 通道 1/3 周期波形 | `sep1` |
| `lwaveb1` / `lwaveb3` | B 通道 1/3 周期波形 | `sep2` |
| `lwave1` / `lwave3` | A/B 合并 1/3 周期波形 | `sep2` |
| `lspecta` / `lspectb` | A/B 模型频谱 | `sep1` / `sep2` |
| `lafc` / `lpfc` | 幅频/相频曲线 | `sweep1` |

成功响应为 `start`、恰好 128 个数字行、`end`。频谱值必须非负。

### 11 条固定长度裸数字命令

| 最终命令 | 原始点数 | 准备命令 |
| --- | ---: | --- |
| `wavea1/a3` | 800 | `sep1` |
| `waveb1/b3`、`wave1/3` | 800 | `sep2` |
| `specta` | 800 | `sep1` |
| `spectb` | 800 | `sep2` |
| `spectrum` | 1024 | `sep1` |
| `afc` / `pfc` | 496 | `sweep1` |

裸流没有 `start/end`。曲线按输出索引压缩到 128 点，频谱每桶保留最大值。

### 准备条件、错误和超时

- `sep1` 接受 `MODEL HIGH/FILTER A READY`，也兼容 AB READY；
- `sep2` 只接受 `MODEL HIGH/FILTER AB READY`，收到仅 A READY 视为远端错误；
- `sweep1` 接受以 `SWEEP DONE` 开头的行；
- 准备阶段的独立 `error`，或包含 `ERROR`/`TIMEOUT` 的行，视为远端错误；
- 数据阶段独立 `error`、错误点数、非数字、错误标志或负频谱都会终止事务。

| 阶段 | 本地超时 |
| --- | ---: |
| 模型准备 | 5 s |
| 扫频准备 | 30 s |
| 帧式 128 点数据 | 2 s |
| 800/1024/496 点裸数据 | 15 s |

查询完整状态：

```c
SerialCommunicationUART3TransactionStatus_e status =
    SerialCommunicationUART3GetTransactionStatus();
```

状态可区分准备模型、准备扫频、收数、完成、远端错误、协议错误和超时。频谱调用方
也可使用简化的 `SerialCommunicationUART3GetSpectrumStatus()`。

UART3 频谱完成后发布给 `FFTAnalysis`；当前调用明确传入空分量列表，因此
`lspect*`、`spect*`、`spectrum` 不会填充 components。上位机 `compa/compb` 的结果
由下述文本命令页显示。

完整协议定义见
[UART3 上位机通信协议](../../../tools/uart3_host_simulator/UART3上位机通信协议.md)。

## UART3 文本控制页面

显示菜单 `UART3 REMOTE` 通过行观察者接收上位机输出。固件已实现以下交互：

| 功能组 | 命令 |
| --- | --- |
| DDS A 频率 | `key01`，等待精确提示 `FREQ(1~1M Hz)`，再发预设数值 |
| DDS A 幅度 | `key02`，等待精确提示 `AMP(0~255)`，再发预设数值 |
| DDS B 相位 | `phase0/45/90/180/270`、`phi90` |
| 建模/模式 | `sep1`、`sep2`、`filter`、`normal`、`filteroff`、`phase`、`ddsphase` |
| 测量/诊断 | `measurea/b`、`compa/b`、`data`、`adcdiag` |
| 模型输出 | `outputa/b`、`output`、`sepouta/b`、`outputoff` |
| 扫频/推理 | `sweep`、`sweep1`、`sweep2`、`infer` |

文本页最多保存 15 个 20 字符片段，一屏 5 个；上位机长行会按 20 字符切分。
S1 短按翻页，S1 长按重发当前命令，S2 长按取消并返回。本地等待超时为 5 s。

`HELLO`/`PING` 是串口 Application 的简单 UART0 调试识别，只输出
`UART3 STRING HELLO/PING` 到 UART0，不会向 UART3 回发应答，也不属于上位机菜单协议。

## DMA 和缓冲资源

- UART1、UART3 RX 使用各自 128 字节静态 Stream Buffer；Application 任务每次取
  最多 64 字节，解析器跨批次保留状态；
- UART2 RX 以 2 字节静态队列项接收；
- UART1/UART2/UART3 发送分别使用各自 DMA 通道和互斥保护；
- PA27/ADC0 使用 DMA_CH5，PB19/ADC1 使用 DMA_CH6；PA21 不再是 ADC1 输入；
- UART3 数据事务保存 128 个 fixed-5 数值，并在完整成功后一次性发布，失败不会
  半更新显示或频谱。

DMA 通道的最终映射以 `blink_led.syscfg` 和生成的 `ti_msp_dl_config.h` 为准，修改
SysConfig 后要重新生成并检查 BSP 宏映射，不能只改文档中的通道号。

## 常见问题

### 发送返回 false

确认对应串口开关已开启并成功初始化，指针非空、长度非零。随后查看
`SerialCommunicationGetTransmitFailureCount()`；若持续增加，检查 DMA 完成中断和
发送超时恢复。

### 接收偶尔丢字节

查看 `SerialCommunicationGetDroppedReceiveCount()`。高吞吐上位机应在命令准备期间
避免无节制输出日志，尤其不要在 800/1024/496 点裸数字中夹杂文字。

### UART2 页面没有波形

确认 USB-TTL TX 接 PB16、共地、每个样本严格为 `AA HH LL 55`。不要把 UART2
输入工具接到 PB15；PB15 是开发板 TX。

### UART3 页面一直等待或显示 TIME

确认 PA26→上位机 RX、PA25←上位机 TX、共地和 115200-8-N-1；确认上位机按 CRLF
识别命令，并在对应截止时间内返回准确 READY、数字数量和帧标志。

### COMPONENT 只显示一个数据

`compa/compb` 是文本结果，不会写入 UART3 频谱 components。文本页每屏只显示有限
行且按 20 字符切片，使用 S1 短按翻页。若上位机把多个分量拼成一条长行，固件会按
显示宽度切分；若只返回一个分量，则下位机不会凭空生成其他分量。
