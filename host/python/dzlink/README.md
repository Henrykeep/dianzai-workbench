# dzlink — dzframe/1 的 Python 实现

给 Linux 协处理板（NVIDIA Jetson Nano、树莓派等）和 PC 工作台用：`protocol.py`（encode / 流式解码 / pack_fields），`channels.py`（按 board.yaml 的 channels 打包/解包），`transport.py`（串口/回环），`workbench.py`（部署、看日志：第 0 阶段预留）。

## 验证状态
- **已实测（PC）**：`python3 -m pytest host/python/dzlink` 或 `make test` 中的回环与 C↔Python 互通测试。
- **未验证**：Jetson Nano 真机串口（设备名、电平、波特率、帧率）。

## 参考来源
见 docs/08-协处理板与软核.md（MAVLink 帧结构、CRC 目录）。
