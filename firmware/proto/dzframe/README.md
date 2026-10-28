# 统一帧协议 dzframe/1  `v1.1.0`

`A5 5A | VER | KIND | ID | SEQ | LEN | PAYLOAD(≤64) | CRC16 LE`，CRC-16/CCITT-FALSE 覆盖 VER..PAYLOAD；显式小端；出错后找下一个 0xA5 重同步。MCU↔Jetson/树莓派/FPGA/另一块 MCU 唯一格式，Python 端见 host/python/dzlink。

- 接口：`dzframe_encode/dzframe_feed/dzframe_put_*/get_*`
- 自检：`dzframe_selftest()`（v1.1.0 新增）；tests/host/test_dzframe.c（含与 Python 实现互通）
- 版本规则：见 docs/03-模块三件套与版本.md（删改声明 = MAJOR，新增 = MINOR，iface_hash 强制）

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：CRC 标准向量、往返、噪声重同步、C↔Python 互通
- **未验证**：真实串口（波特率、长线干扰）**未实测**

## 参考来源
- MAVLink v1 帧结构（mavlink.io：SOF+LEN+SEQ+ID+CRC 的思路）；CRC 参数取自 Greg Cook CRC 目录 reveng.sourceforge.io/crc-catalogue（CRC-16/CCITT-FALSE，check=0x29B1）
