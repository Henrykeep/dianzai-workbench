# RTT 链路 dzrtt  `v0.1.0`

让 LINK（dzframe/dzctl）走调试探针的 SEGGER RTT 通道 0，**不占串口**：编译时 `make LINK=rtt ...` 打开（默认仍走 `RES_UART_LINK` 串口）。上位机端口选 `rtt:<目标>[@探针]`（需要 pyOCD）。

- 控制块布局与 SEGGER RTT 一致（ID `SEGGER RTT`，1 上行 + 1 下行），pyOCD / J-Link / OpenOCD 都能找到；不含 SEGGER 源码。
- 非阻塞：上行满了整段丢（DZ_EBUSY），和串口 EBUSY 丢帧一样；每段要么全写要么不写，不会把一帧拆坏。
- 应用通过 `apps/include/link_io.h` 的 `link_write / link_read / link_tx_idle` 收发，开关只在这一处。

## 验证状态
- **已实测（PC）**：tests/host 单元测试（模拟探针读写环形缓冲、回绕、满了丢、ID 只在初始化后出现）。
- **未验证**：真实探针 + MSPM0/STM32 上的 RTT 吞吐和时延【未上板】；上行缓冲 1 KB 在探针轮询慢时可能丢遥测（丢的是整帧，上位机按 CRC 重新同步）。

## 参考来源
- SEGGER RTT 控制块格式（SEGGER_RTT.h 公开文档的结构体布局）；pyOCD `pyocd/debug/rtt.py` 的读写方式（核对过：读 RdOff..WrOff，写 WrOff 后更新）。
