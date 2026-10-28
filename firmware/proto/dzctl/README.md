# 上位机控制服务 dzctl  `v0.1.0`

dzframe/1 之上的三件事：**参数读写（板端限幅、回传生效值）**、**急停**、**带 schema 哈希的心跳**。桌面工作台（app/）和 Agent 都只通过它改板上参数。

| 方向 | 帧 | 负载 |
|---|---|---|
| PC→板 | PARAM_SET id=序号 | 空 = 读；f32 = 写 |
| 板→PC | PARAM_ACK id=序号 | u8 status（0 OK / 1 已限幅 / 2 序号错 / 3 长度错 / 4 NaN·Inf 拒绝）, f32 生效值 |
| PC→板 | DATA id=0x7F | 空：急停（应用锁存） |
| PC→板 | DATA id=0x7E | u8 命令字符（应用自定义） |
| 板→PC | HEARTBEAT | u32 schema_hash，上位机据此找 `link_schema.json`；0.3.0 起再跟 u32 board_uid（芯片 UID 折成 32 位，0 = 未知；F1/F4 读 UID，MSPM0 读 FACTORYREGION TRACEID/USERID，上板【未测】）。旧上位机只读前 4 字节，兼容 |

参数表、遥测打包函数和 `link_schema.json` 由 `tools/gen_link.py` 从 yaml 的 `link:` 段生成，C 与上位机同源。

## 验证状态
- **已实测（PC）**：`dzctl_selftest()`、tests/host 单元测试、host-sim 与桌面 sidecar 的端到端测试（app/sidecar/tests）。
- **未验证**：真实串口上的参数写入时序（写参数与控制中断并发：f32 对齐写在 Cortex-M 上是原子的，非对齐/多字段组合不保证）。

## 参考来源
- MAVLink 参数协议（mavlink.io/en/services/parameter.html）：SET 后回传实际值、上位机以回传为准。
- PX4 参数元数据（min/max/unit 与代码同源生成）的思路。
