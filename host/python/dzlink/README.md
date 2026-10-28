# dzlink — dzframe/1 的 Python 实现

给 Linux 协处理板（NVIDIA Jetson Nano、树莓派等）和 PC 工作台用：`protocol.py`（encode / 流式解码 / pack_fields），`channels.py`（按 board.yaml 的 channels 打包/解包），`transport.py`（串口/回环）。

## 验证状态
- **已实测（PC）**：`python3 -m pytest host/python/dzlink` 或 `make test` 中的回环与 C↔Python 互通测试。
- **未验证**：Jetson Nano 真机串口（设备名、电平、波特率、帧率）。

## 参考来源
见 docs/08-协处理板与软核.md（MAVLink 帧结构、CRC 目录）。

## 1.1.0：发送端与串口自动探测
`sender.py`（Sender：按通道打包、seq、截断、限速、心跳；MaixCAM 自动用 maix.uart）、`autodetect.py`（平台识别 + 心跳探测选口）。
K230（MicroPython）用 `host/k230/dzsend.py`。用法见 docs/22-协处理器发送库.md。
