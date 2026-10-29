# peerlink — 两车 / 车机状态链路

| 帧 | DATA id | 内容 |
|---|---|---|
| STATE | 0x70 | u32 t_ms, f32 s_m（里程）, v_mps, x_m, y_m, yaw_rad, u16 flags（RUNNING/MARK/STOPPED），26 字节 |
| ABORT | 0x71 | u16 reason；**本地先停车再连发 3 帧**，收方锁存，人确认 `peer_rx_clear_abort` |

收方丢重复/乱序（seq 差不在 1..127）、长度不对、非有限值；`peer_rx_fresh` = 收到过 + 没超 `stale_ms` + 没中止。
跟车控制见 `firmware/algo/follow`。走 dzframe，所以任何透传无线模块都能用；与上位机共用一个串口时 id 不冲突（0x7D..0x7F 归 dzctl）。

来源：DS-land-and-air LoRa 联调规范（固定时隙、新鲜度/CRC/乱序、中止三帧不延迟关电机），见 docs/参考来源.md。[仿真]
