# UART3 当前实现速查

本页是导航，不是独立协议真相。修改前必须核对：

- `application/communication/serial_communication/serial_communication.h`
- `application/communication/serial_communication/serial_communication.c`
- `application/menu/display_menu/display_menu.c`
- `application/app_config.h`

`tools/uart3_host_simulator/UART3上位机通信协议.md` 已按当前实现重写，并在文末单独
保留 `wave1\0/components\0/spectrum\0` 历史附录。当前新交互由固件发送 `\r\n`
结尾命令，两者不能混为一套状态机。

## 数值数据请求

`SerialCommunicationUART3DataType_e` 目前有 21 种：

| 响应格式 | 命令 | 上位机返回点数 | 本地处理 |
| --- | --- | ---: | --- |
| `start` + 数字行 + `end` | `lwavea1/lwavea3/lwaveb1/lwaveb3/lwave1/lwave3` | 128 | fixed-5 转 milli-unit，发布 128 个样本 |
| 同上 | `lspecta/lspectb` | 128 | 发布为 UART3 外部频谱 |
| 同上 | `lafc/lpfc` | 128 | 转换并发布为 128 点曲线样本 |
| 固定长度裸数字行 | `wavea1/wavea3/waveb1/waveb3/wave1/wave3` | 800 | 缩减到 128 点后发布 |
| 固定长度裸数字行 | `specta/spectb` | 800 | 每个输出桶保留峰值，发布 128 点外部频谱 |
| 固定长度裸数字行 | `spectrum` | 1024 | 每个输出桶保留峰值，发布 128 点外部频谱 |
| 固定长度裸数字行 | `afc/pfc` | 496 | 缩减到 128 点后作为曲线样本发布 |

所有请求字符串在当前源码中以 `\r\n` 结束。带 `l` 的 128 点响应严格要求
`start`、恰好 128 个可解析数字、`end`。裸流不带 start/end，达到固定点数即完成。
数字解析使用普通十进制 fixed-5 规则，不应发送科学计数法；频谱不允许负数。

## 自动准备阶段

`SerialCommunicationUART3RequestPreparedData()` 会先建立上位机数据，再自动发最终查询：

- A 单通道模型：`sep1`，适用于 A 波形、A 频谱以及当前 `spectrum` 映射。
- B 或 A/B 合并模型：`sep2`，适用于 B、A/B 波形和 B 频谱。
- 幅频/相频曲线：`sweep1`，适用于 `lafc/lpfc/afc/pfc`。

模型阶段接受 `MODEL HIGH A READY`、`MODEL FILTER A READY`、
`MODEL HIGH AB READY`、`MODEL FILTER AB READY` 中与请求相容的行；扫频等待以
`SWEEP DONE` 开头的行。准备日志会被事务层消费，不当作数据点。

特别注意：`start` 是最终数据命令已经发出之后的 128 点帧头，不是 `sep1/sep2` 的
准备成功标志。可选 `AA + int16 大端 + 55` 通用采样解析也不是这些新数据事务的帧格式。

进入 UART3 波形或频谱页面、切换到 UART3 来源以及长按重新测量，当前菜单都会调用
prepared request，因此自动执行一次相应 `sep1/sep2` 或 `sweep1`。通用 API
`SerialCommunicationUART3RequestData()` 可以直接查询已经存在的数据，但不能据此假定
当前菜单会跳过准备阶段；具体操作必须核对 `display_menu.c` 的按键分支。

## 状态、错误与超时

事务状态：`IDLE -> PREPARING_MODEL/PREPARING_SWEEP -> COLLECTING -> COMPLETE`，失败可到
`REMOTE_ERROR`、`PROTOCOL_ERROR` 或 `TIMEOUT`。

- 128 点带帧响应本地超时 2 s。
- 800/1024/496 点裸响应本地超时 15 s。
- `sep1/sep2` 准备超时 5 s；`sweep1` 准备超时 30 s。
- `error`、包含 `ERROR`/`TIMEOUT` 的准备响应、非法数字、提前/多余 `end`、负频谱等都
  会进入正式错误状态。
- `SerialCommunicationUART3CancelRequest()` 清本地状态；无法终止上位机已开始的运算。
- 完成或失败后的迟到文本会被丢弃，不能落回旧逐行采样路径。

## 文本命令页面

`UART3 REMOTE` 菜单直接实现这些交互：

- `key01`：等待 `FREQ(1~1M Hz)`，再发送预置频率行。
- `key02`：等待 `AMP(0~255)`，再发送预置幅度行。
- 相位：`phase<number>`、`phi<number>`。
- 模式：`sep1`、`sep2`、`filter`、`normal`、`filteroff`、`phase`、`ddsphase`。
- 读回：`measurea`、`measureb`、`compa`、`compb`、`data`、`adcdiag`。
- 输出：`outputa`、`outputb`、`output`、`sepouta`、`sepoutb`、`outputoff`。
- 扫频/推理：`sweep`、`sweep1`、`sweep2`、`infer`。

文本页会消费并保存多行响应：最多 15 个显示片段，每片 20 字符，每页显示 5 片；短按
下一键翻页，长按下一键重发，长按返回键退出。等待首个/下一阶段响应的本地超时为 5 s，
错误关键词会显示 ERR。因此判断 `compa/compb` 是否完整显示时，要同时检查上位机是否逐行
发送、15 片容量以及用户是否翻页，不能只看屏幕当前一页。

当前 `SerialCommunicationUART3CompleteTransaction()` 调用
`FFTAnalysisPublishExternalSpectrum(..., NULL, 0U, ...)`，所以新 UART3 频谱事务不发布
分量列表；`APP_UART3_SPECTRUM_MAX_COMPONENT_COUNT` 只是保留兼容配置。`compa/compb`
结果仅由文本页显示。若只看到一个分量，应检查上位机实际返回、20 字符切片、15 片容量
和是否继续翻页，不能把文本结果当作频谱分量结构。

## 审计清单

对每条命令回答以下问题：发送入口和用户操作、终止符、准备命令、成功标志、数据点数与
单位、解析状态、发布者、页面容量/翻页、错误、超时、取消和实板验证。任何一项缺失都不能
宣称“通信已完整兼容”。
