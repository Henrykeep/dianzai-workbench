# 显示菜单波形与频谱数据指南

`display_menu.c` 使用 128×64 逻辑画布显示本地 ADC、UART2 和 UART3 数据；OLED
与 TFT 共用完全相同的数据路径。页面是按次采集、整帧冻结显示，不是后台滚动示波器。

## 来源总览

| 页面来源 | 输入数据 | 页面使用的数据 |
| --- | --- | --- |
| ADC PA27 | ADC0.0，一次性 DMA | 配置窗口的最后 128 点 |
| ADC PB19 | ADC1.6，一次性 DMA，默认关闭 | 配置窗口的最后 128 点 |
| UART2 PB16 | `AA + int16 大端 + 55` | 收满 1024 点后的最后 128 点 |
| UART3 `lwave*`/`lafc`/`lpfc` | `start`、128 个数字、`end` | 原样 128 点 |
| UART3 `wave*` | 800 个裸数字 | 压缩到 128 点 |
| UART3 `afc`/`pfc` | 496 个裸数字 | 压缩到 128 点 |
| 本地 FFT | ADC 或 UART2 的一帧 FFT | 32 个显示频带及主峰/分量 |
| UART3 `lspect*` | `start`、128 个非负数字、`end` | 128 点外部频谱 |
| UART3 `spect*` | 800 个裸非负数字 | 每个输出频带保留最大值 |
| UART3 `spectrum` | 1024 个裸非负数字 | 每个输出频带保留最大值 |

PB19 是当前第二路物理 ADC。源码为兼容旧项目，部分类型名仍包含 `PA21`；PA21
现在只保留给第二路 COMP2 周期捕获，不是 ADC1 输入。

## 本地 ADC 波形

选择 `WAVEFORM → ADC PA27` 或已启用的 `ADC PB19` 会立即发起一次完整测量。
当前 PA27 默认为 1024 点、1 MHz，窗口约 1.024 ms；PB19 默认关闭，启用后的
默认点数和速率相同。采样、FFT 和参数计算完成后页面冻结，后续 ADC 不会自动刷新。

显示前把 12 位原始码减去 2048，得到以 ADC 中点为零的有符号值。页面只取最后
128 点，不做平均或重采样；若整帧点数正好为 128，则全部点与屏幕横向列一一对应。

本地频率优先使用可用的 COMP + Timer Capture；没有可靠捕获时回退到 FFT 主峰。
第二路电压样本来自 PB19，而可选捕获脚是 PA21。两者需要表示同一信号时必须在
外部同时送入，不能把 PB19 的 ADC 接线误接到 PA21。

## UART2 波形

UART2 引脚为 PB15/TX、PB16/RX，115200-8-N-1。每个样本固定 4 字节：

```text
0xAA  DATA_H  DATA_L  0x55
```

`DATA_H/DATA_L` 是有符号 `int16_t` 大端值。接收任务通过订阅接口发布合法样本；
波形页面收满 1024 点后显示最后 128 点。帧头、帧尾不匹配时解析器重新寻找
`0xAA`，不会把无效帧发布给页面。

常用订阅接口：

```c
bool SerialCommunicationUART2SubscribeSample(
    SerialCommunicationUART2SampleCallback_t callback, void *context);

bool SerialCommunicationUART2UnsubscribeSample(
    SerialCommunicationUART2SampleCallback_t callback, void *context);
```

回调在 UART2 接收任务上下文执行，必须快速、非阻塞。取消订阅后最多还可能收到
一次已经取得快照的回调，`context` 不能立刻失效。

## UART3 接线与命令结尾

| 开发板 | 上位机/USB-TTL |
| --- | --- |
| PA26 / UART3 TX | RX |
| PA25 / UART3 RX | TX |
| GND | GND |

通信参数为 115200-8-N-1。固件发出的新协议命令全部以 `\r\n` 结束，不是旧资料
中的 NUL。上位机返回的每个文本标志和数字也应按行结束；固件同时接受 CR、LF 或
CRLF 作为接收行边界。

## UART3 自动准备流程

用户从菜单进入曲线或频谱页时调用
`SerialCommunicationUART3RequestPreparedData()`：

```text
A 通道模型数据   → sep1 → 等待 MODEL ... READY → 最终命令
B/AB 模型数据    → sep2 → 等待 AB MODEL ... READY → 最终命令
幅频/相频数据    → sweep1 → 等待 SWEEP DONE → 最终命令
```

因此进入 `UART3 LWAVE A1` 会自动完成一次 SEP1 测量，然后发送 `lwavea1`；
进入 `UART3 LWAVE 1` 会自动执行 SEP2；进入 `UART3 LAFC` 会自动执行 SWEEP1。
S1 长按重测当前页面时会重新走同样的准备流程。

`SerialCommunicationUART3RequestData()` 只发送最终数据命令，适合调用方已经明确
完成准备的场景。不要把它误当作菜单“重新测量”接口。

## 十条 128 点帧式命令

| 命令 | 内容 | 自动准备 |
| --- | --- | --- |
| `lwavea1` / `lwavea3` | A 通道 1/3 周期波形 | `sep1` |
| `lwaveb1` / `lwaveb3` | B 通道 1/3 周期波形 | `sep2` |
| `lwave1` / `lwave3` | A/B 合并 1/3 周期波形 | `sep2` |
| `lspecta` / `lspectb` | A/B 128 点模型频谱 | `sep1` / `sep2` |
| `lafc` / `lpfc` | 128 点幅频/相频曲线 | `sweep1` |

成功响应必须严格为：

```text
start
<数字 1>
...
<数字 128>
end
```

帧外杂项文本会被行观察者或旧文本处理消费；进入帧后，非数字、点数不足/过多、
错误的 `start/end` 次序都会得到协议错误。频谱数字不能为负。

## 十一条裸数字命令

| 命令 | 原始点数 | 本地处理 | 自动准备 |
| --- | ---: | --- | --- |
| `wavea1/a3`、`waveb1/b3`、`wave1/3` | 800 | 按输出索引保留代表点 | `sep1` 或 `sep2` |
| `specta`、`spectb` | 800 | 每个输出索引保留最大频谱值 | `sep1` 或 `sep2` |
| `spectrum` | 1024 | 每个输出索引保留最大频谱值 | `sep1` |
| `afc`、`pfc` | 496 | 按输出索引保留代表点 | `sweep1` |

裸流没有 `start/end`，固件按命令预期点数判断完成。上位机不得在数字流中夹入普通
提示行；否则事务会判定为错误，而不是继续猜测。

## 状态和超时

UART3 数据事务状态包括：空闲、准备模型、准备扫频、收数、完成、上位机错误、
协议错误和超时。页面对应显示 `PREP`、`SWEEP`、`WAIT`、`DONE`、`ERROR` 或 `TIME`。

| 阶段 | 本地超时 |
| --- | ---: |
| `sep1`/`sep2` 模型准备 | 5 s |
| `sweep1` 扫频准备 | 30 s |
| `start + 128 + end` 帧式数据 | 2 s |
| 800/1024/496 点裸数据 | 15 s |

收到独立 `error` 或明显错误提示会进入上位机错误；格式或数量不符合协议进入协议
错误。退出页面、切换来源时调用 `SerialCommunicationUART3CancelRequest()` 清空
本地事务，迟到的旧响应不会被当成下一次数据。

## UART3 通用样本订阅

除请求/响应协议外，UART3 还可解析两类独立样本：

- `AA + int16 大端 + 55`；
- 逐行 ASCII 电压，如 `0.57385\r\n`。

它们分别由 `APP_ENABLE_UART3_BINARY_WAVEFORM` 和
`APP_ENABLE_UART3_ASCII_WAVEFORM` 控制，并通过以下接口发布：

```c
bool SerialCommunicationUART3SubscribeSample(
    SerialCommunicationUART3SampleCallback_t callback, void *context);

bool SerialCommunicationUART3UnsubscribeSample(
    SerialCommunicationUART3SampleCallback_t callback, void *context);
```

不要把通用样本流与 21 条菜单数据命令混在同一事务中发送。

## 页面操作

| 页面 | S1 短按 | S1 长按 | S2 短按 | S2 长按 |
| --- | --- | --- | --- | --- |
| 波形 | 向上切换 Y 轴量程 | 当前来源重新测量 | 循环切换来源 | 返回 |
| 频谱 | 循环切换来源 | 当前来源重新测量 | 分量列表/翻页 | 返回 |

UART3 数据频谱当前不带 components 列表；`compa`、`compb` 返回内容由 UART3 文本
页按行显示。`APP_UART3_SPECTRUM_MAX_COMPONENT_COUNT` 是保留的兼容配置，不会让
新 `lspect*`/`spect*` 事务自动产生分量。

## 常见问题

### 进入 UART3 页面立即 TIME

检查 PA26→上位机 RX、PA25←上位机 TX、共地和 115200-8-N-1；确认上位机识别
CRLF 命令，并在对应准备时间内返回精确 READY 文本。

### 显示 ERROR

检查是否返回了独立 `error`、负频谱、非数字、错误点数或错误帧标志。帧式响应必须
正好 128 个数字；裸流必须正好 800、1024 或 496 个数字。

### 波形有较大直流偏置

UART3 默认按接收电压原样显示。若只想让图像围绕中线，可开启
`APP_ENABLE_UART3_WAVEFORM_DISPLAY_REMOVE_DC`；这不会改变原始数据或频谱。

### 切换来源后出现上一页数据

正常退出路径会取消事务并丢弃迟到行。自定义页面若直接调用底层接口，应在离开或
切换来源前显式调用 `SerialCommunicationUART3CancelRequest()`。

完整协议定义见
[UART3 上位机通信协议](../../../tools/uart3_host_simulator/UART3上位机通信协议.md)。
