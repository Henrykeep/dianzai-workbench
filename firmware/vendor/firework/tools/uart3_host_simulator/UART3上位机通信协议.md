# UART3 上位机通信协议

本文描述当前 `freertos_firework` 下位机在 UART3 上主动发送的协议。当前数据和
文本命令都以 CRLF 结束；旧版 `wave1\0 → components\0 → spectrum\0` 仅保留在
文末兼容附录和模拟器中，不是当前菜单事务。

## 串口和接线

| 参数 | 值 |
| --- | --- |
| 波特率 | 115200 bit/s |
| 数据格式 | 8-N-1，无流控 |
| 文本编码 | ASCII |
| 固件命令结尾 | `\r\n` |
| 上位机响应行结尾 | 推荐 `\r\n`；固件也接受 CR、LF 或 NUL |

| 开发板 | USB-TTL/上位机 |
| --- | --- |
| PA26 / UART3 TX | RX |
| PA25 / UART3 RX | TX |
| GND | GND |

设备名可能是 `/dev/ttyUSB*` 或 `/dev/ttyACM*`，以实际 USB 串口枚举为准。不要把
UART3 和 PA10/UART0 调试口混淆。

## 通道复用

UART3 同时承载四类内容：

1. 下位机主动发送的 21 条数据命令及上位机数字响应；
2. `UART3 REMOTE` 页面发送的文本控制命令及上位机文本结果；
3. 可选的通用 `AA + int16 大端 + 55` 或 ASCII 电压样本；
4. 矩阵键盘发送的“单字符 + NUL”。

数据事务进行时，上位机不能把调试日志插入数字流。一次只允许一个准备/收数事务；
控制页面也应等当前数据页完成、取消或超时后再发新业务数据。

## 21 条数据命令总表

### 帧式 128 点命令

| 命令 | 返回内容 | 准备命令 |
| --- | --- | --- |
| `lwavea1` / `lwavea3` | A 通道 1/3 周期、128 点波形 | `sep1` |
| `lwaveb1` / `lwaveb3` | B 通道 1/3 周期、128 点波形 | `sep2` |
| `lwave1` / `lwave3` | A/B 合并 1/3 周期、128 点波形 | `sep2` |
| `lspecta` | A 通道 128 点模型频谱 | `sep1` |
| `lspectb` | B 通道 128 点模型频谱 | `sep2` |
| `lafc` / `lpfc` | 128 点幅频/相频曲线 | `sweep1` |

成功响应必须严格为：

```text
start\r\n
<number[0]>\r\n
...
<number[127]>\r\n
end\r\n
```

- 恰好 128 个普通十进制数；允许符号、小数和两侧空白，不支持科学计数法；
- 固件内部最多保留 5 位小数，随后按页面需要换算；
- `lspecta/lspectb` 的频谱数必须非负；
- `end` 提前、点数超出、非数字或 128 点后不是 `end` 都是协议错误；
- `start` 前的准备日志会忽略，帧内不能夹日志。

### 固定长度裸数字命令

| 命令 | 返回行数 | 内容 | 准备命令 |
| --- | ---: | --- | --- |
| `wavea1` / `wavea3` | 800 | A 通道波形 | `sep1` |
| `waveb1` / `waveb3` | 800 | B 通道波形 | `sep2` |
| `wave1` / `wave3` | 800 | A/B 合并波形 | `sep2` |
| `specta` | 800 | A 通道模型频谱 | `sep1` |
| `spectb` | 800 | B 通道模型频谱 | `sep2` |
| `spectrum` | 1024 | ADC0 原始 FFT 频谱 | `sep1` |
| `afc` / `pfc` | 496 | 原始幅频/相频曲线 | `sweep1` |

裸响应没有 `start/end`，上位机直接逐行发送精确数量的数字。波形/曲线按输入索引
映射到 128 点并保留每个输出位置的代表值；频谱每个输出桶保留最大值，避免窄峰
在压缩中消失。频谱数字必须非负。

当前 `wave1` 和 `spectrum` 与旧协议同名，但当前语义分别是 800 和 1024 行，
不能按旧版只返回 128 行。

## 自动准备状态机

菜单进入曲线/频谱页和 S1 长按重测都使用“准备后请求”接口：

```text
用户选择数据
   ├─ A 模型数据  → 发送 sep1
   ├─ B/AB 数据   → 发送 sep2
   └─ 幅相频数据  → 发送 sweep1
            ↓
       等待 READY / DONE
            ↓
       自动发送最终数据命令
            ↓
       校验并发布完整结果
```

### `sep1` 完成条件

下位机接受以下任一精确行：

```text
MODEL HIGH A READY
MODEL FILTER A READY
MODEL HIGH AB READY
MODEL FILTER AB READY
```

接受 AB READY 是为了兼容上位机已经建立双通道模型的情况。

### `sep2` 完成条件

只接受：

```text
MODEL HIGH AB READY
MODEL FILTER AB READY
```

如果此时只返回 A READY，下位机立即判定远端错误，因为 B/AB 数据尚未准备好。

### `sweep1` 完成条件

接受任何以以下文本开头的行：

```text
SWEEP DONE
```

例如 `SWEEP DONE type=0 points=496` 合法。其他扫描进度行在准备阶段被消费，不会
进入数字解析。

## 错误与超时

上位机无法完成当前请求时，应单独返回：

```text
error\r\n
```

准备阶段包含 `ERROR` 或 `TIMEOUT` 的行也被视为远端失败。数字阶段的独立
`error`、负频谱、非数字、错误点数或错误帧标志会终止事务。

| 阶段 | 下位机本地超时 |
| --- | ---: |
| `sep1` / `sep2` 模型建立 | 5 s |
| `sweep1` 扫频 | 30 s |
| 帧式 128 点响应 | 2 s |
| 800/1024/496 点裸响应 | 15 s |

下位机状态能区分远端错误、协议错误和超时，菜单分别结束等待并显示 `ERROR` 或
`TIME`。退出页面会取消本地事务；这不能停止上位机已经开始的计算，但迟到数据会
被丢弃，不能复用为下一请求。

## 数字范围与单位

UART3 事务只规定普通十进制行和点数，具体物理单位由命令语义决定：

- 波形和幅频/相频曲线通常按上位机的工程定义输出；下位机将 fixed-5 值四舍五入
  到 milli-unit，并饱和到显示使用的 `int16_t`；
- 频谱按非负相对幅值处理，并由 `FFTAnalysis` 归一化为柱状图；
- UART3 频谱横轴当前配置为 0～500 kHz，128 点映射到该范围；
- 新频谱事务当前不随数据返回 components。`compa/compb` 是独立文本命令，其结果
  在文本页显示。

上位机应避免科学计数法、NaN 和 Inf。若数值超出 fixed-5 的 32 位范围，解析失败。

## 文本控制命令

`UART3 REMOTE` 页面发送以下命令，全部带 CRLF。

### 两阶段参数设置

频率：

```text
下位机 → key01\r\n
上位机 → FREQ(1~1M Hz)\r\n
下位机 → <100|1000|10000|100000|1000000>\r\n
```

幅度：

```text
下位机 → key02\r\n
上位机 → AMP(0~255)\r\n
下位机 → <0|64|128|192|255>\r\n
```

提示必须与上面文本精确匹配，大小写、空格和波浪号都不能改变。参数页等待总超时
为 5 s。

### 直接文本命令

| 功能 | 命令 |
| --- | --- |
| 建立模型 | `sep1`、`sep2` |
| 滤波模式 | `filter`；`normal` 或 `filteroff` 关闭 |
| PLL | `phase`、`ddsphase` |
| DDS B 相位 | `phase0/45/90/180/270`、`phi90` |
| 测量 | `measurea`、`measureb` |
| 分量 | `compa`、`compb` |
| 诊断 | `data`、`adcdiag` |
| 模型输出 | `outputa`、`outputb`、`output` |
| 分量分离输出 | `sepouta`、`sepoutb` |
| 关闭输出 | `outputoff` |
| 扫频 | `sweep`、`sweep1`、`sweep2` |
| 谐波推理 | `infer` |

上位机可以返回多行文本。下位机最多保存 15 个 20 字符片段，一屏显示 5 个；
长行会切片。S1 短按翻页，S1 长按重新发送当前命令，S2 长按取消并退出。
`error` 或明显错误文本应作为正式失败响应，不要只打印错误后继续输出成功数据。

`phase<number>` / `phi<number>` 由上位机解释数字并设置 DDS B 相位；当前菜单提供
固定预设，但上位机实现可以支持协议说明中的完整数字范围。

## 频率分量显示说明

`compa`/`compb` 的返回格式由上位机文本定义，下位机不把它解析进 FFT 分量结构，
而是原样切成 20 字符片段显示。若 COMPONENT 页面看起来只有一个值：

1. S1 短按查看后续页面；
2. 检查上位机是否确实输出多行/多个分量；
3. 不要期待先执行 `lspecta` 后自动出现 `compa` 数据。

## 矩阵键盘上报

`APP_ENABLE_MATRIX_KEYPAD_UART3_OUTPUT=1U` 时，每个新按下键发送：

```text
[一个 ASCII 键值] [00]
```

例如 `5` 为 `35 00`。有效布局：

```text
1  2  3  A
4  5  6  B
7  8  9  C
*  0  #  D
```

只发送新的按下事件，不发送保持或释放。这个 NUL 只属于键盘上报，不改变所有
下位机主动文本/数据命令都用 CRLF 的规则。

## 可选通用样本流

数据请求之外，上位机还可主动发送：

```text
AA HIGH LOW 55
```

其中 `HIGH/LOW` 是有符号 `int16_t` 毫值的大端补码；或者发送逐行 ASCII 电压，
例如 `0.57385\r\n`。这两种流分别受
`APP_ENABLE_UART3_BINARY_WAVEFORM` 和 `APP_ENABLE_UART3_ASCII_WAVEFORM` 控制，
通过 UART3 样本订阅接口发布。不要在 21 条数据事务中混入通用样本流。

`HELLO` 和 `PING` 只让下位机在 UART0 打印调试提示，不会从 UART3 回 ACK，不能
用作链路握手。

## 推荐上位机实现

1. 二进制方式打开串口，关闭软件换行转换；
2. 接收端同时识别 CR、LF 和 NUL，忽略 CRLF 产生的空 token；
3. 用发送锁保证一次响应的行不与其他日志交叉；
4. `sep`/`sweep` 完成后先发送 READY/DONE，再等待下位机的最终命令；
5. 帧式命令发送 `start + 128 + end`；裸式命令发送精确固定行数；
6. 失败时发送独立 `error` 并结束本事务；
7. 为 1024 行响应预留足够吞吐，但总耗时必须小于 15 s；
8. 收到新准备命令时取消或隔离上一轮计算，避免旧 READY 和新事务串线。

## 当前模拟器覆盖范围

`tools/uart3_host_simulator/server.py` 当前可用于：

- `sep1`、`sep2`、`sweep`、`sweep1` 准备响应；
- 6 条 `lwave*`、`lafc`、`lpfc`、`lspecta`、`lspectb`，即当前全部 10 条
  帧式 128 点命令；
- 矩阵键盘 NUL 上报；
- 文末旧版三命令协议。

它尚未实现当前 8 条 800 点命令、`spectrum` 的 1024 点新语义、`afc/pfc` 的
496 点新语义，也未实现 `UART3 REMOTE` 全部文本命令。因此它不是完整上位机的
替代品；测试未覆盖命令时应使用最新上位机或扩展模拟器。

## 旧版兼容附录

旧项目曾使用：

```text
下位机 → wave1\0       上位机 → 128 个裸 ASCII 电压
下位机 → components\0  上位机 → 数量 + 若干频率/幅值
下位机 → spectrum\0    上位机 → 128 个裸非负频谱值
```

当前固件菜单不再发送 `components\0`，当前 `wave1`/`spectrum` 即使名字相同也已经
改为 CRLF 且分别需要 800/1024 点。只有维护旧固件或测试模拟器兼容分支时才使用
本附录，不能据此实现当前上位机。

## 相关编译开关

| 开关 | 当前默认 | 作用 |
| --- | ---: | --- |
| `APP_ENABLE_UART3` | 1 | UART3 总开关 |
| `APP_ENABLE_UART3_WAVEFORM_REQUEST` | 1 | 曲线数据事务和菜单项 |
| `APP_ENABLE_UART3_SPECTRUM` | 1 | 外部频谱事务和菜单项 |
| `APP_ENABLE_UART3_ASCII_WAVEFORM` | 1 | 空闲状态 ASCII 样本流 |
| `APP_ENABLE_UART3_BINARY_WAVEFORM` | 1 | `AA + int16 + 55` 样本流 |
| `APP_ENABLE_UART3_TEXT_COMMAND` | 1 | 兼容 HELLO/PING 调试处理 |
| `APP_ENABLE_UART3_WAVEFORM_DISPLAY_REMOVE_DC` | 0 | 只对 UART3 波形显示副本去直流 |
| `APP_ENABLE_MATRIX_KEYPAD_UART3_OUTPUT` | 1 | 矩阵键值字符 + NUL |
